#!/usr/bin/env python3
"""Build pubget-grounded silver GT for NeuroimageMetaAnalysis Harbor JSON.

This script creates:
1) a sidecar GT bundle JSON keyed by task id,
2) a doc-binding CSV (task -> fixed PMCID/PMC URL/PDF URL),
3) optional in-place patching of Harbor tasks to reference GT and fix doc_id.

It is designed as a deterministic bootstrap. The resulting GT is "silver"
auto-generated and should be spot-checked before paper-grade release.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "use",
    "using",
    "with",
    "only",
    "provided",
    "frozen",
    "corpus",
    "study",
    "studies",
    "paper",
    "papers",
    "json",
    "schema",
    "evidence",
    "spans",
    "support",
    "claims",
    "return",
    "task",
    "meta",
    "analysis",
    "screening",
    "eligibility",
    "extract",
    "extraction",
}

FMRI_HINTS = (
    "fmri",
    "functional magnetic resonance",
    "functional mri",
    "bold",
    "blood oxygen level dependent",
    "resting-state",
    "resting state",
)
HUMAN_HINTS = (
    "human",
    "participants",
    "subjects",
    "patients",
    "healthy",
    "adults",
    "adolescent",
    "children",
)
NON_PRIMARY_HINTS = ("review", "meta-analysis", "systematic review")
REST_HINTS = ("resting-state", "resting state", "rest")
TASK_HINTS = (
    "task",
    "go/no-go",
    "n-back",
    "stroop",
    "emotion",
    "reward",
    "memory",
    "cue",
    "trial",
)
PHRASE_HINTS = (
    "working memory",
    "resting state",
    "resting-state",
    "default mode",
    "major depressive",
    "schizophrenia",
    "bipolar",
    "anxiety",
    "pain",
    "emotion regulation",
    "reward",
    "fear",
    "executive function",
    "attention",
    "seed-based",
    "whole-brain",
    "whole brain",
    "functional connectivity",
    "multivariate pattern",
    "mvpa",
    "smoothing",
    "fwhm",
    "talairach",
    "mni",
)


def _setup_csv_limit() -> None:
    # Large Pubget text fields can exceed the python csv default limit.
    max_int = sys.maxsize
    while True:
        try:
            csv.field_size_limit(max_int)
            break
        except OverflowError:
            max_int = int(max_int / 10)


def normalize_doc_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper().startswith("PMC"):
        digits = re.sub(r"[^0-9]", "", text)
        return f"PMC{digits}" if digits else ""
    digits = re.sub(r"[^0-9]", "", text)
    return f"PMC{digits}" if digits else ""


def to_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_year_window(question: str) -> tuple[int, int] | None:
    years = [int(x) for x in re.findall(r"(?:19|20)\d{2}", question)]
    if not years:
        return None
    return (min(years), max(years))


def has_fmri_hint(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in FMRI_HINTS)


def extract_query_terms(question: str) -> tuple[list[str], list[str]]:
    q = question.lower()
    tokens = re.findall(r"[a-z][a-z0-9\-]{2,}", q)
    filtered = [t for t in tokens if len(t) >= 4 and t not in STOPWORDS]
    # Keep deterministic uniqueness order.
    seen: set[str] = set()
    uniq_tokens: list[str] = []
    for tok in filtered:
        if tok not in seen:
            seen.add(tok)
            uniq_tokens.append(tok)
    phrases = [p for p in PHRASE_HINTS if p in q]
    return uniq_tokens[:16], phrases


def sentence_split(text: str) -> list[str]:
    if not text.strip():
        return []
    chunks = re.split(r"(?<=[.!?])\s+", text.strip())
    return [c.strip() for c in chunks if c.strip()]


@dataclass(frozen=True)
class DocRecord:
    doc_id: str
    pmcid_digits: str
    pmid: str
    doi: str
    title: str
    year: int | None
    license: str
    keywords: str
    abstract: str
    has_tables: bool
    blob: str

    @property
    def pmc_article_url(self) -> str:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{self.doc_id}/"

    @property
    def pmc_pdf_url(self) -> str:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{self.doc_id}/pdf/"


def load_table_presence(tables_csv: Path) -> set[str]:
    seen: set[str] = set()
    with tables_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            doc_id = normalize_doc_id(row.get("pmcid"))
            if doc_id:
                seen.add(doc_id)
    return seen


def load_metadata(metadata_csv: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with metadata_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            doc_id = normalize_doc_id(row.get("pmcid"))
            if not doc_id:
                continue
            out[doc_id] = {
                "pmid": str(row.get("pmid") or "").strip(),
                "doi": str(row.get("doi") or "").strip(),
                "title": str(row.get("title") or "").strip(),
                "year": to_int(row.get("publication_year")),
                "license": str(row.get("license") or "").strip(),
            }
    return out


def load_fmri_docs(
    metadata: dict[str, dict[str, Any]],
    text_csv: Path,
    table_presence: set[str],
) -> list[DocRecord]:
    docs: dict[str, DocRecord] = {}
    with text_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            doc_id = normalize_doc_id(row.get("pmcid"))
            if not doc_id:
                continue
            if doc_id not in metadata:
                continue

            base = metadata[doc_id]
            title = str(row.get("title") or base.get("title") or "").strip()
            keywords = str(row.get("keywords") or "").strip()
            abstract = str(row.get("abstract") or "").strip()
            blob = " ".join([title, keywords, abstract]).lower()
            if not has_fmri_hint(blob):
                continue

            pmcid_digits = re.sub(r"[^0-9]", "", doc_id)
            candidate = DocRecord(
                doc_id=doc_id,
                pmcid_digits=pmcid_digits,
                pmid=str(base.get("pmid") or ""),
                doi=str(base.get("doi") or ""),
                title=title,
                year=to_int(base.get("year")),
                license=str(base.get("license") or ""),
                keywords=keywords,
                abstract=abstract,
                has_tables=doc_id in table_presence,
                blob=blob,
            )
            # Keep the richer abstract if duplicates appear.
            current = docs.get(doc_id)
            if current is None or len(candidate.abstract) > len(current.abstract):
                docs[doc_id] = candidate
    return sorted(docs.values(), key=lambda d: d.doc_id)


def rank_docs(
    docs: list[DocRecord],
    task_id: str,
    question: str,
    limit: int = 5,
) -> tuple[list[DocRecord], dict[str, Any]]:
    query_tokens, phrase_tokens = extract_query_terms(question)
    year_window = parse_year_window(question)
    ranked: list[tuple[int, int, str, DocRecord, list[str]]] = []

    for doc in docs:
        score = 0
        overlap: list[str] = []
        for token in query_tokens:
            if token in doc.blob:
                score += 2
                overlap.append(token)
        for phrase in phrase_tokens:
            if phrase in doc.blob:
                score += 5
                overlap.extend(phrase.split())
        if year_window and doc.year is not None:
            if year_window[0] <= doc.year <= year_window[1]:
                score += 2
        ranked.append((score, doc.year or -1, doc.doc_id, doc, sorted(set(overlap))))

    ranked.sort(key=lambda x: (-x[0], -x[1], x[2]))
    winners: list[DocRecord] = [x[3] for x in ranked if x[0] > 0][:limit]

    if not winners:
        # Deterministic fallback when no lexical overlap found.
        if not docs:
            return [], {"query_tokens": query_tokens, "phrases": phrase_tokens, "top_score": 0}
        start = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest(), 16) % len(docs)
        for i in range(min(limit, len(docs))):
            winners.append(docs[(start + i) % len(docs)])

    top_overlap = []
    if ranked:
        top_overlap = ranked[0][4]

    debug = {
        "query_tokens": query_tokens,
        "phrases": phrase_tokens,
        "year_window": year_window,
        "top_score": ranked[0][0] if ranked else 0,
        "top_overlap": top_overlap,
    }
    return winners, debug


def make_quote(doc: DocRecord, terms: list[str]) -> str:
    if doc.abstract:
        for sentence in sentence_split(doc.abstract):
            lower = sentence.lower()
            if any(t in lower for t in terms[:8]) and len(sentence) >= 40:
                return sentence[:400]
        first = sentence_split(doc.abstract)[:1]
        if first:
            return first[0][:400]
        return doc.abstract[:400]
    return doc.title[:400]


def infer_mode(blob: str) -> str:
    lower = blob.lower()
    has_rest = any(term in lower for term in REST_HINTS)
    has_task = any(term in lower for term in TASK_HINTS)
    if has_rest and has_task:
        return "both"
    if has_task:
        return "task"
    if has_rest:
        return "rest"
    return "unclear"


def infer_study_type(blob: str) -> str:
    mode = infer_mode(blob)
    if mode in {"task", "both"}:
        return "task-fMRI"
    if mode == "rest":
        return "resting-state"
    return "other"


def infer_screening_include(blob: str) -> bool:
    lower = blob.lower()
    has_human = any(term in lower for term in HUMAN_HINTS)
    non_primary = any(term in lower for term in NON_PRIMARY_HINTS)
    return has_fmri_hint(lower) and has_human and not non_primary


def infer_scope(blob: str) -> str:
    lower = blob.lower()
    has_wb = "whole-brain" in lower or "whole brain" in lower
    has_roi = "roi" in lower or "region of interest" in lower
    if has_wb and has_roi:
        return "both"
    if has_wb:
        return "whole_brain"
    if has_roi:
        return "roi_only"
    return "unclear"


def infer_coordinates(blob: str) -> tuple[str, str]:
    lower = blob.lower()
    has_coords = bool(re.search(r"\bmni\b|\btalairach\b|coordinate", lower))
    has_mni = "mni" in lower
    has_tal = "talairach" in lower
    if has_mni and has_tal:
        return ("yes", "MNI/Talairach")
    if has_mni:
        return ("yes", "MNI")
    if has_tal:
        return ("yes", "Talairach")
    if has_coords:
        return ("partial", "unclear")
    return ("no", "unclear")


def extract_n_total(text: str) -> int | None:
    patterns = (
        r"\bn\s*=\s*(\d{1,4})\b",
        r"\b(\d{1,4})\s+(?:participants|subjects|patients|controls)\b",
        r"\bincluded\s+(\d{1,4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def extract_age_features(text: str) -> tuple[float | None, str | None]:
    lower = text.lower()
    mean_match = re.search(r"(?:mean age|age mean|mean)\s*(?:of|=)?\s*(\d{1,2}(?:\.\d+)?)", lower)
    age_mean = float(mean_match.group(1)) if mean_match else None
    range_match = re.search(r"(\d{1,2}\s*[-–]\s*\d{1,2}\s*(?:years|yrs|y)?)", lower)
    age_range = range_match.group(1) if range_match else None
    return age_mean, age_range


def extract_smoothing_mm(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(
        r"(\d{1,2}(?:\.\d+)?)\s*mm(?:\s*fwhm|\s*gaussian|\s*smoothing)?",
        text.lower(),
    ):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if 1.0 <= value <= 20.0:
            values.append(value)
    return values


def make_evidence_span(doc: DocRecord, quote: str) -> dict[str, Any]:
    return {
        "doc_id": doc.doc_id,
        "source": "pubget_text",
        "quote": quote,
        "section": "abstract",
    }


def make_silver_answer(
    schema_name: str,
    question: str,
    primary: DocRecord,
    selected: list[DocRecord],
    overlap_terms: list[str],
) -> dict[str, Any]:
    quote = make_quote(primary, overlap_terms)
    span = make_evidence_span(primary, quote)
    blob = primary.blob
    score_hint = max(1, len(overlap_terms))
    include = infer_screening_include(blob)
    mode = infer_mode(blob)
    coords_reported, coord_space = infer_coordinates(blob)
    scope = infer_scope(blob)
    n_total = extract_n_total(primary.abstract or primary.title)
    age_mean, age_range = extract_age_features(primary.abstract or primary.title)
    correction = bool(re.search(r"\bfwe\b|\bfdr\b|multiple comparisons|corrected", blob))
    year_window = parse_year_window(question)

    if schema_name == "screening_binary":
        return {
            "include_for_screening": include,
            "study_type": infer_study_type(blob),
            "evidence_spans": [span],
        }
    if schema_name == "screening_mode":
        return {
            "fmri_mode": mode,
            "evidence_spans": [span],
        }
    if schema_name == "screening_relevance":
        decision = "include" if score_hint >= 2 and include else "exclude"
        return {
            "decision": decision,
            "reasons": [f"keyword overlap: {', '.join(overlap_terms[:6]) or 'weak'}"],
            "missing_info_needed": [],
            "evidence_spans": [span],
        }
    if schema_name == "screening_coords":
        return {
            "coordinates_reported": coords_reported,
            "coordinate_space": coord_space,
            "tables_present": primary.has_tables,
            "evidence_spans": [span],
        }
    if schema_name == "screening_scope":
        return {
            "analysis_scope": scope,
            "evidence_spans": [span],
        }
    if schema_name == "screening_sample_threshold":
        return {
            "n_total": n_total,
            "n_by_group": {},
            "passes_threshold": bool(n_total and n_total >= 20),
            "evidence_spans": [span],
        }
    if schema_name == "eligibility_decision":
        decision = "include" if include else ("maybe" if score_hint >= 2 else "exclude")
        return {
            "decision": decision,
            "criteria_checks": {
                "primary_human_fmri": include,
                "coordinates_reported": coords_reported in {"yes", "partial"},
                "reporting_sufficient": bool(primary.abstract),
            },
            "rationale_spans": [span],
            "missing_info": [] if decision != "maybe" else ["insufficient detail in abstract"],
        }
    if schema_name == "eligibility_operationalization":
        return {
            "diagnosis_operationalization": "extract from abstract methods and inclusion text",
            "decision_impact": "include" if include else "maybe",
            "evidence_spans": [span],
        }
    if schema_name == "eligibility_age":
        eligible = age_mean is None or age_mean >= 16.0
        return {
            "age_mean": age_mean,
            "age_range": age_range,
            "eligible": eligible,
            "subgroup_extractable": bool(age_range),
        }
    if schema_name == "eligibility_task_match":
        task_match = "yes" if score_hint >= 3 else ("partial" if score_hint >= 1 else "no")
        decision = "include" if task_match == "yes" else ("maybe" if task_match == "partial" else "exclude")
        return {
            "task_match": task_match,
            "deviation_notes": [] if task_match == "yes" else ["partial lexical alignment only"],
            "decision": decision,
        }
    if schema_name == "eligibility_contrast_mapping":
        contrast_found = bool(re.search(r"\bvs\b|>\s*|contrast|compared with", blob))
        return {
            "contrast_found": contrast_found,
            "direction": "reported" if contrast_found else "unclear",
            "mappable": contrast_found,
            "mapping_rule": "extract contrast A vs B from methods/results" if contrast_found else None,
            "evidence_spans": [span],
        }
    if schema_name == "eligibility_wb_correction":
        wb = scope in {"whole_brain", "both"}
        return {
            "whole_brain_inference": wb,
            "multiple_comparisons_correction": correction,
            "exclude_reason_if_any": None if (wb and correction) else "missing WB correction evidence",
        }
    if schema_name == "eligibility_overlap":
        return {
            "overlap_detected": False,
            "overlapping_studies": [],
            "recommendation": "manual cross-check with author/year and cohort description",
        }
    if schema_name == "extraction_generic":
        return {
            "fields": {
                "doc_id": primary.doc_id,
                "title": primary.title,
                "year": primary.year,
                "doi_or_pmid": primary.doi or primary.pmid,
                "study_type": infer_study_type(blob),
                "fmri_mode": mode,
                "analysis_scope": scope,
                "coordinates_reported": coords_reported,
            },
            "evidence_spans": [span],
        }
    if schema_name == "discovery_study_list":
        if year_window:
            years = {"start": year_window[0], "end": year_window[1]}
        else:
            year_values = [d.year for d in selected if d.year is not None]
            years = {
                "start": min(year_values) if year_values else 1990,
                "end": max(year_values) if year_values else datetime.now(timezone.utc).year,
            }
        matching = []
        for doc in selected[:8]:
            matching.append(
                {
                    "title": doc.title,
                    "year": int(doc.year or 0),
                    "doi_or_pmid": doc.doi or doc.pmid or doc.doc_id,
                    "task": infer_study_type(doc.blob),
                    "key_contrasts": [],
                }
            )
        return {
            "topic": question[:120],
            "population": "mixed/unspecified",
            "years": years,
            "matching_studies": matching,
            "missing_areas": [],
        }
    if schema_name == "discovery_analysis_coverage":
        counts = {"whole_brain": 0, "roi_only": 0, "both": 0, "unclear": 0}
        for doc in selected:
            counts[infer_scope(doc.blob)] += 1
        return {
            "analysis_types_covered": counts,
            "underexplored": [],
        }
    if schema_name == "discovery_task_distribution":
        buckets: dict[str, int] = {}
        for doc in selected:
            key = infer_study_type(doc.blob)
            buckets[key] = buckets.get(key, 0) + 1
        distribution = [{"task": k, "count": v} for k, v in sorted(buckets.items())]
        rare = [item["task"] for item in distribution if item["count"] == 1]
        return {
            "task_distribution": distribution,
            "rare_tasks": rare,
            "missing_tasks_hypothesis": [],
        }
    if schema_name == "discovery_contrast_inconsistency":
        return {
            "construct": ", ".join(overlap_terms[:5]) or "unspecified construct",
            "contrast_definitions": [
                {"doc_id": doc.doc_id, "label": doc.title[:120]} for doc in selected[:6]
            ],
            "inconsistencies": [],
        }
    if schema_name == "discovery_demographic_coverage":
        age_values = []
        for doc in selected:
            age_mean_doc, _ = extract_age_features(doc.abstract)
            if age_mean_doc is not None:
                age_values.append(age_mean_doc)
        return {
            "age_coverage_summary": {
                "n_with_age": len(age_values),
                "mean_age_estimate": round(sum(age_values) / len(age_values), 3)
                if age_values
                else None,
            },
            "sex_coverage_summary": {"notes": "requires full-text extraction for robust coding"},
            "underrepresented_groups": [],
        }
    if schema_name == "discovery_smoothing_trend":
        values: list[float] = []
        by_year: dict[int, list[float]] = {}
        for doc in selected:
            mm_values = extract_smoothing_mm(doc.abstract)
            values.extend(mm_values)
            if doc.year is not None and mm_values:
                by_year.setdefault(doc.year, []).extend(mm_values)
        summary = {
            "count_values": len(values),
            "min_mm": min(values) if values else None,
            "max_mm": max(values) if values else None,
        }
        return {
            "smoothing_values_mm": sorted(set(round(v, 3) for v in values)),
            "summary_stats": summary,
            "by_year": [
                {"year": year, "values_mm": sorted(set(round(v, 3) for v in vals))}
                for year, vals in sorted(by_year.items())
            ],
        }
    if schema_name == "discovery_oa_limitation":
        return {
            "likely_missing": [],
            "reason": "OA corpus coverage may miss paywalled or delayed OA publications.",
            "followup_queries": [],
        }

    # Generic fallback for unknown schema names.
    return {
        "note": "schema not explicitly handled",
        "evidence_spans": [span],
    }


def schema_name_from_task(task: dict[str, Any]) -> str:
    outputs = task.get("expected_outputs", [])
    for item in outputs:
        if isinstance(item, dict) and "output_schema_ref" in item:
            ref = str(item["output_schema_ref"])
            return ref.rsplit("/", maxsplit=1)[-1]
    input_schema = task.get("input", {}).get("schema_ref")
    if input_schema:
        return str(input_schema).rsplit("/", maxsplit=1)[-1]
    return "unknown"


def add_or_replace_gt_output(task: dict[str, Any], gt_ref: str) -> None:
    outputs = task.get("expected_outputs")
    if not isinstance(outputs, list):
        outputs = []

    gt_item = {
        "id": "gt_primary",
        "kind": "gt_solution",
        "title": "Pubget Silver GT",
        "visibility": "authenticated",
        "format": "json",
        "content": {
            "gt_ref": gt_ref,
            "gt_quality": "silver_auto_v1",
            "source_policy": "pubget_json_only",
        },
    }

    replaced = False
    for idx, item in enumerate(outputs):
        if not isinstance(item, dict):
            continue
        if item.get("id") == "gt_primary" or item.get("kind") == "gt_solution":
            outputs[idx] = gt_item
            replaced = True
            break
    if not replaced:
        outputs.append(gt_item)
    task["expected_outputs"] = outputs


def build_gt(
    harbor_json_path: Path,
    metadata_csv: Path,
    text_csv: Path,
    tables_csv: Path,
    out_gt_json: Path,
    out_bindings_csv: Path,
    write_back_harbor: bool,
) -> dict[str, Any]:
    _setup_csv_limit()
    harbor = json.loads(harbor_json_path.read_text(encoding="utf-8"))
    tasks: list[dict[str, Any]] = harbor.get("tasks", [])
    if not tasks:
        raise ValueError(f"No tasks found in {harbor_json_path}")

    metadata = load_metadata(metadata_csv)
    table_presence = load_table_presence(tables_csv)
    docs = load_fmri_docs(metadata, text_csv, table_presence)
    if not docs:
        raise ValueError("No fMRI-like documents found in pubget text index.")

    gt_by_task: dict[str, Any] = {}
    binding_rows: list[dict[str, Any]] = []
    fixed_doc_count = 0

    gt_rel_ref_prefix = f"{out_gt_json.parent.name}/{out_gt_json.name}"

    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        input_block = task.get("input", {})
        question = str(
            input_block.get("question")
            or task.get("instruction")
            or task.get("description")
            or task_id
        )
        schema_name = schema_name_from_task(task)
        selected_docs, debug_info = rank_docs(docs, task_id=task_id, question=question, limit=8)
        if not selected_docs:
            continue
        primary = selected_docs[0]
        overlap_terms = list(debug_info.get("top_overlap") or debug_info.get("query_tokens") or [])
        quote = make_quote(primary, overlap_terms)
        silver_answer = make_silver_answer(
            schema_name=schema_name,
            question=question,
            primary=primary,
            selected=selected_docs,
            overlap_terms=overlap_terms,
        )

        requires_doc = "doc_id" in input_block
        if requires_doc:
            old_doc = str(input_block.get("doc_id") or "")
            if old_doc == "REQUIRED_AT_RUN_TIME" or not normalize_doc_id(old_doc):
                input_block["doc_id"] = primary.doc_id
                fixed_doc_count += 1
            input_block["doc_id_source"] = input_block.get("doc_id_source") or "pubget::pmcid"
            input_block["doc_id_format"] = input_block.get("doc_id_format") or "PMC<digits>"

        gt_ref = f"{gt_rel_ref_prefix}#/task_gt/{task_id}"
        add_or_replace_gt_output(task, gt_ref=gt_ref)

        metadata_block = task.get("metadata") or {}
        metadata_block["gt_available"] = True
        metadata_block["gt_quality"] = "silver_auto_v1"
        metadata_block["gt_ref"] = gt_ref
        task["metadata"] = metadata_block

        gt_by_task[task_id] = {
            "task_id": task_id,
            "schema_name": schema_name,
            "question": question,
            "suite": metadata_block.get("suite") or input_block.get("task_mode"),
            "doc_binding": {
                "doc_id": primary.doc_id,
                "pmcid_digits": primary.pmcid_digits,
                "title": primary.title,
                "year": primary.year,
                "doi": primary.doi,
                "pmid": primary.pmid,
                "license": primary.license,
                "pmc_article_url": primary.pmc_article_url,
                "pmc_pdf_url": primary.pmc_pdf_url,
            },
            "candidate_docs": [
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "year": doc.year,
                    "doi_or_pmid": doc.doi or doc.pmid,
                    "pmc_article_url": doc.pmc_article_url,
                    "pmc_pdf_url": doc.pmc_pdf_url,
                }
                for doc in selected_docs[:8]
            ],
            "evidence_anchor": make_evidence_span(primary, quote),
            "silver_answer": silver_answer,
            "selection_debug": debug_info,
            "quality": "silver_auto_v1",
            "source_policy": "pubget_json_only",
        }

        binding_rows.append(
            {
                "task_id": task_id,
                "schema_name": schema_name,
                "doc_id": primary.doc_id,
                "pmcid_digits": primary.pmcid_digits,
                "title": primary.title,
                "year": "" if primary.year is None else str(primary.year),
                "doi": primary.doi,
                "pmid": primary.pmid,
                "pmc_article_url": primary.pmc_article_url,
                "pmc_pdf_url": primary.pmc_pdf_url,
            }
        )

    gt_bundle = {
        "dataset_id": harbor.get("dataset", {}).get("id"),
        "dataset_version": harbor.get("dataset", {}).get("version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/build_meta_gt_from_pubget.py",
        "quality": "silver_auto_v1",
        "source_policy": "pubget_json_only",
        "source_paths": {
            "metadata_csv": str(metadata_csv),
            "text_csv": str(text_csv),
            "tables_csv": str(tables_csv),
        },
        "stats": {
            "task_count": len(gt_by_task),
            "doc_fixed_count": fixed_doc_count,
            "candidate_doc_pool": len(docs),
        },
        "task_gt": gt_by_task,
    }

    out_gt_json.write_text(
        json.dumps(gt_bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if binding_rows:
        fieldnames = list(binding_rows[0].keys())
        with out_bindings_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(binding_rows)

    dataset_block = harbor.get("dataset", {})
    dataset_block["gt_bundle"] = {
        "path": f"{out_gt_json.parent.name}/{out_gt_json.name}",
        "quality": "silver_auto_v1",
        "generated_at": gt_bundle["generated_at"],
        "source_policy": "pubget_json_only",
    }
    harbor["dataset"] = dataset_block

    if write_back_harbor:
        harbor_json_path.write_text(
            json.dumps(harbor, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "harbor_json": str(harbor_json_path),
        "out_gt_json": str(out_gt_json),
        "out_bindings_csv": str(out_bindings_csv),
        "stats": gt_bundle["stats"],
        "write_back_harbor": write_back_harbor,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build pubget-grounded silver GT for NeuroimageMetaAnalysis.",
    )
    parser.add_argument("--harbor-json", required=True, type=Path)
    parser.add_argument("--metadata-csv", required=True, type=Path)
    parser.add_argument("--text-csv", required=True, type=Path)
    parser.add_argument("--tables-csv", required=True, type=Path)
    parser.add_argument("--out-gt-json", required=True, type=Path)
    parser.add_argument("--out-bindings-csv", required=True, type=Path)
    parser.add_argument(
        "--write-back-harbor",
        action="store_true",
        help="Patch Harbor JSON in place (doc_id binding + gt_primary refs).",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    result = build_gt(
        harbor_json_path=args.harbor_json,
        metadata_csv=args.metadata_csv,
        text_csv=args.text_csv,
        tables_csv=args.tables_csv,
        out_gt_json=args.out_gt_json,
        out_bindings_csv=args.out_bindings_csv,
        write_back_harbor=args.write_back_harbor,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
