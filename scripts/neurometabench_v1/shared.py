#!/usr/bin/env python3
"""Shared data utilities for the NeurometaBench v1 harness."""

from __future__ import annotations

import csv
import json
import random
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "external" / "neurometabench" / "data"
DEFAULT_CASES_PATH = REPO_ROOT / "benchmarks" / "neurometabench" / "cases.v1.jsonl"
DEFAULT_NEUROSYNTH_DATA_DIR = REPO_ROOT / "data" / "neurosynth_nimare" / "neurosynth"
LAYER_A_SCREENING = "layer_a_screening_with_justification"
LAYER_B_REPRODUCTION = "layer_b_end_to_end_reproduction"
LAYER_C_DIAGNOSTIC_AUDIT = "layer_c_diagnostic_audit"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sort_pmids(pmids: Iterable[str]) -> list[str]:
    def _key(pmid: str) -> tuple[int, str]:
        return (int(pmid), pmid) if str(pmid).isdigit() else (10**20, str(pmid))

    return sorted({str(p).strip() for p in pmids if str(p).strip()}, key=_key)


def normalize_folder_name(topic_name: str) -> str:
    normalized = topic_name.lower()
    normalized = normalized.replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def load_meta_rows(data_dir: Path = DEFAULT_DATA_DIR) -> list[dict[str, str]]:
    return read_csv_rows(data_dir / "meta_datasets.csv")


def load_ground_truth_by_meta(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, set[str]]:
    gt: dict[str, set[str]] = {}
    src = data_dir / "included_studies.csv"
    if not src.exists():
        return gt
    for row in read_csv_rows(src):
        meta_pmid = (row.get("meta_pmid") or "").strip()
        study_pmid = (row.get("study_pmid") or "").strip()
        if meta_pmid and study_pmid:
            gt.setdefault(meta_pmid, set()).add(study_pmid)
    return gt


def load_closed_world_candidates(data_dir: Path, meta_pmid: str) -> list[str]:
    src = data_dir / "all_studies.csv"
    if not src.exists():
        return []
    pmids: list[str] = []
    seen: set[str] = set()
    for row in read_csv_rows(src):
        if (row.get("meta_pmid") or "").strip() != meta_pmid:
            continue
        study_pmid = (row.get("study_pmid") or "").strip()
        if study_pmid and study_pmid not in seen:
            seen.add(study_pmid)
            pmids.append(study_pmid)
    return pmids


def load_closed_world_candidate_rows(data_dir: Path, meta_pmid: str) -> list[dict[str, str]]:
    """Load closed-world candidate rows, preferring annotated metadata when available."""

    for filename in ("all_studies_annotated_wt.csv", "all_studies_annotated.csv", "all_studies.csv"):
        src = data_dir / filename
        if not src.exists():
            continue
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in read_csv_rows(src):
            if (row.get("meta_pmid") or "").strip() != meta_pmid:
                continue
            study_pmid = (row.get("study_pmid") or "").strip()
            if not study_pmid or study_pmid in seen:
                continue
            seen.add(study_pmid)
            rows.append(row)
        return rows
    return []


def load_all_study_universe(data_dir: Path) -> list[str]:
    pmids: list[str] = []
    seen: set[str] = set()
    for filename in ("all_studies.csv", "included_studies.csv"):
        src = data_dir / filename
        if not src.exists():
            continue
        for row in read_csv_rows(src):
            pmid = (row.get("study_pmid") or "").strip()
            if pmid and pmid not in seen:
                seen.add(pmid)
                pmids.append(pmid)
    return pmids


def load_mixed_pool_candidates(
    data_dir: Path,
    meta_pmid: str,
    *,
    noise_ratio: int = 5,
    seed: int = 0,
    max_total: int | None = None,
) -> list[str]:
    """Build a deterministic GT + random non-GT candidate pool.

    The pool is intended for screening stress tests when a curated closed-world
    candidate list is unavailable. With ``noise_ratio=5``, the expected base
    rate is approximately 1 included study per 6 candidates.
    """

    gt = sort_pmids(load_ground_truth_by_meta(data_dir).get(meta_pmid, set()))
    if not gt:
        return []
    universe = [pmid for pmid in load_all_study_universe(data_dir) if pmid not in set(gt)]
    rng = random.Random(f"{seed}:{meta_pmid}:mixed_pool")
    rng.shuffle(universe)
    n_noise_target = max(0, int(noise_ratio)) * len(gt)
    if max_total is not None:
        # Preserve every GT PMID so mixed_pool remains a screening stress test,
        # not an accidental retrieval-failure test. If len(gt) exceeds max_total,
        # return all GT rather than silently lowering candidate recall.
        n_noise_target = min(n_noise_target, max(0, int(max_total) - len(gt)))
    n_noise = min(len(universe), n_noise_target)
    pool = list(gt) + universe[:n_noise]
    rng.shuffle(pool)
    return pool


def _criterion_id(text: str, prefix: str) -> str:
    lower = text.lower()
    if "peer-reviewed" in lower or "peer reviewed" in lower:
        return f"{prefix}_peer_reviewed"
    if "adult human" in lower or ("adult" in lower and "human" in lower):
        return f"{prefix}_adult_humans"
    if "english" in lower:
        return f"{prefix}_english_language"
    if "gray matter" in lower or "grey matter" in lower:
        return f"{prefix}_gray_matter_structure"
    if "voxel-based morphometry" in lower or "vbm" in lower:
        if "non" in lower or "other" in lower:
            return f"{prefix}_non_vbm_methods"
        return f"{prefix}_vbm"
    if "not measuring ptsd" in lower or ("ptsd" in lower and "not" in lower):
        return f"{prefix}_not_ptsd"
    if "treatment" in lower or "longitudinal" in lower:
        return f"{prefix}_treatment_longitudinal"
    if "within-group" in lower or "within group" in lower:
        return f"{prefix}_within_group"
    if "null effect" in lower:
        return f"{prefix}_null_effects"
    if "overlapping" in lower or "overlap" in lower:
        return f"{prefix}_overlapping_samples"
    if "whole" in lower and "brain" in lower:
        return f"{prefix}_whole_brain"
    if "coordinate" in lower or "talairach" in lower or "mni" in lower:
        return f"{prefix}_coordinates_reported"
    if "roi" in lower or "region of interest" in lower:
        return f"{prefix}_roi_only"
    if "healthy" in lower and ("adult" in lower or "age" in lower):
        return f"{prefix}_healthy_adults"
    if "original" in lower or "empirical" in lower:
        return f"{prefix}_original_data"
    if "psychiatric" in lower or "neurological" in lower:
        return f"{prefix}_clinical_population"
    tokens = [
        token
        for token in re.findall(r"[a-z][a-z0-9]+", lower)
        if token
        not in {
            "and",
            "among",
            "brain",
            "criteria",
            "data",
            "english",
            "human",
            "included",
            "language",
            "meta",
            "only",
            "paper",
            "papers",
            "participants",
            "reporting",
            "results",
            "studies",
            "study",
            "the",
            "with",
        }
    ]
    slug = "_".join(tokens[:4]) or "criterion"
    return f"{prefix}_{slug}"


def _split_criteria(text: str) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    cleaned = re.sub(r"\s+", " ", cleaned)
    parts = re.split(r"\s*(?:;|\n+|\s+\d+\)|\s+\d+\.)\s*", cleaned)
    if len(parts) == 1 and "," in cleaned:
        comma_text = re.sub(r",?\s+and\s+", ", ", cleaned)
        parts = [part.strip() for part in comma_text.split(",")]
    out: list[str] = []
    for part in parts:
        part = re.sub(r"^\s*(?:\d+\)|\d+\.|First,|Second,|Third,)\s*", "", part.strip())
        part = part.strip(" .;")
        if part and len(part) >= 8:
            out.append(part)
    return out or [cleaned]


def build_screening_criteria(inclusion: str, exclusion: str) -> list[dict[str, str]]:
    criteria: list[dict[str, str]] = []
    seen: set[str] = set()
    for polarity, prefix, text in (
        ("include", "inc", inclusion),
        ("exclude", "exc", exclusion),
    ):
        for item in _split_criteria(text):
            cid = _criterion_id(item, prefix)
            if cid in seen:
                suffix = 2
                while f"{cid}_{suffix}" in seen:
                    suffix += 1
                cid = f"{cid}_{suffix}"
            seen.add(cid)
            criteria.append({"criterion_id": cid, "polarity": polarity, "text": item})
    return criteria


def assign_task_layers(route: str, closed_world_candidate_count: int, has_gt: bool) -> dict[str, Any]:
    layers: list[str] = []
    if has_gt and route != "nimads_brainmap":
        layers.append(LAYER_A_SCREENING)
    if route == "nimads_brainmap":
        layers.append(LAYER_B_REPRODUCTION)
    if not layers:
        layers.append(LAYER_C_DIAGNOSTIC_AUDIT)
    elif LAYER_C_DIAGNOSTIC_AUDIT not in layers:
        layers.append(LAYER_C_DIAGNOSTIC_AUDIT)
    primary = layers[0]
    task_type = {
        LAYER_A_SCREENING: "screening_with_justification",
        LAYER_B_REPRODUCTION: "end_to_end_reproduction",
        LAYER_C_DIAGNOSTIC_AUDIT: "diagnostic_audit",
    }[primary]
    return {"task_layers": layers, "primary_task_layer": primary, "task_type": task_type}


def build_layer_c_contract(route: str, has_gt: bool) -> dict[str, Any]:
    audits = [
        {
            "audit_id": "retrieval_ceiling",
            "required": bool(has_gt),
            "metric": "candidate_recall",
            "interpretation": "separates candidate retrieval coverage from screening quality",
        },
        {
            "audit_id": "neurovault_substrate",
            "required": True,
            "metric": "gt_neurovault_collection_coverage",
            "interpretation": "estimates whether substrate-level map comparison is possible",
        },
    ]
    if route == "nimads_brainmap":
        audits.append(
            {
                "audit_id": "nimads_asset_audit",
                "required": True,
                "metric": "path_b_status",
                "interpretation": "checks whether structured coordinates support Layer B reproduction",
            }
        )
    return {
        "layer": LAYER_C_DIAGNOSTIC_AUDIT,
        "role": "diagnostic_audit_not_headline_score",
        "headline_score": False,
        "audits": audits,
    }


def find_nimads_assets(data_dir: Path, topic: str) -> dict[str, Any]:
    project_key = normalize_folder_name(topic)
    project_dir = data_dir / "nimads" / project_key
    if not project_dir.exists():
        return {
            "project_key": project_key,
            "project_dir": None,
            "raw_jsons": [],
            "merged_studyset": None,
            "merged_annotation": None,
        }

    raw_jsons = sorted(str(path) for path in project_dir.glob("*.json") if path.is_file())
    merged_dir = project_dir / "merged"
    studyset = merged_dir / "nimads_studyset.json"
    annotation = merged_dir / "nimads_annotation.json"
    return {
        "project_key": project_key,
        "project_dir": str(project_dir),
        "raw_jsons": raw_jsons,
        "merged_studyset": str(studyset) if studyset.exists() else None,
        "merged_annotation": str(annotation) if annotation.exists() else None,
    }


def _pmc_digits(value: str) -> str:
    return re.sub(r"[^0-9]", "", value or "")


def find_local_pmc_bundle(data_dir: Path, meta_pmid: str, pmcid: str) -> Path | None:
    root = data_dir / "meta-studies" / "pmc-oa"
    if not root.exists():
        return None
    target_pmcid = _pmc_digits(pmcid)
    for metadata_csv in root.rglob("metadata.csv"):
        try:
            for row in read_csv_rows(metadata_csv):
                row_pmid = (row.get("pmid") or "").strip()
                row_pmcid = _pmc_digits(row.get("pmcid") or "")
                if row_pmid == meta_pmid or (target_pmcid and row_pmcid == target_pmcid):
                    return metadata_csv.parents[1]
        except Exception:
            continue
    return None


def resolve_case_route(row: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    topic = (row.get("topic") or "").strip()
    method = (row.get("method") or "").strip()
    additional_methods = (row.get("additional_methods") or "").strip()
    search = (row.get("search") or "").strip()
    pmid = (row.get("pmid") or "").strip()
    pmcid = (row.get("pmcid") or "").strip()

    nimads_assets = find_nimads_assets(data_dir, topic)
    local_pmc_bundle = find_local_pmc_bundle(data_dir, pmid, pmcid)
    has_pmc = bool(pmcid) or local_pmc_bundle is not None
    brainmap_like = any(
        marker in f"{method} {additional_methods} {search}".lower()
        for marker in ("brainmap", "data-driven clustering", "image-based meta-analysis")
    )

    if brainmap_like and nimads_assets["project_dir"]:
        route = "nimads_brainmap"
        workflow = "analysis_reproduction"
        reason = "BrainMap/NiMADS-backed case with available project assets."
    elif has_pmc:
        route = "pmc_fulltext"
        workflow = "screening_from_fulltext"
        reason = "Meta-analysis has PMCID or local PMC-OA coverage."
    else:
        route = "pubmed_metadata"
        workflow = "screening_from_metadata"
        reason = "No NiMADS route or PMC full-text asset; use metadata search."

    return {
        "official_route": route,
        "recommended_workflow": workflow,
        "dispatch_reason": reason,
        "nimads_assets": nimads_assets,
        "pmc_assets": {
            "pmcid": pmcid or None,
            "local_bundle": str(local_pmc_bundle) if local_pmc_bundle else None,
        },
    }


def derive_year_cutoff(row: dict[str, Any]) -> int | None:
    dates = (row.get("dates") or "").strip()
    years = [int(match) for match in re.findall(r"(?:19|20)\d{2}", dates)]
    if years:
        return max(years)
    criteria_text = " ".join(
        [
            row.get("search") or "",
            row.get("additional_methods") or "",
        ]
    )
    criteria_years = [int(match) for match in re.findall(r"(?:19|20)\d{2}", criteria_text)]
    if criteria_years:
        return max(criteria_years)
    year = (row.get("year") or "").strip()
    return int(year) if year.isdigit() else None


def build_case_record(
    row: dict[str, str],
    data_dir: Path,
    gt_by_meta: dict[str, set[str]],
) -> dict[str, Any]:
    meta_pmid = (row.get("pmid") or "").strip()
    gt_pmids = sort_pmids(gt_by_meta.get(meta_pmid, set()))
    dispatch = resolve_case_route(row, data_dir)
    closed_world_candidate_count = len(load_closed_world_candidates(data_dir, meta_pmid))
    task_assignment = assign_task_layers(dispatch["official_route"], closed_world_candidate_count, bool(gt_pmids))
    screening_criteria = build_screening_criteria(
        (row.get("inclusion") or "").strip(),
        (row.get("exclusion") or "").strip(),
    )
    return {
        "case_id": f"neurometabench:{meta_pmid}",
        "benchmark": "neurometabench",
        "track": "study_set_reconstruction_v1",
        "meta_pmid": meta_pmid,
        "pmcid": (row.get("pmcid") or "").strip() or None,
        "year": int(row["year"]) if (row.get("year") or "").isdigit() else None,
        "year_cutoff": derive_year_cutoff(row),
        "topic": (row.get("topic") or "").strip(),
        "method": (row.get("method") or "").strip(),
        "modality": (row.get("modality") or "").strip(),
        "search": (row.get("search") or "").strip(),
        "additional_methods": (row.get("additional_methods") or "").strip(),
        "inclusion": (row.get("inclusion") or "").strip(),
        "exclusion": (row.get("exclusion") or "").strip(),
        "search_results_n": (row.get("search_results_n") or "").strip() or None,
        "selected_n": (row.get("selected_n") or "").strip() or None,
        "analyses": (row.get("analyses") or "").strip(),
        "screening_criteria": screening_criteria,
        "gt_pmids": gt_pmids,
        "n_gt": len(gt_pmids),
        "has_gt": bool(gt_pmids),
        "closed_world_candidate_count": closed_world_candidate_count,
        "route": dispatch["official_route"],
        **task_assignment,
        "layer_c_diagnostic_contract": build_layer_c_contract(
            dispatch["official_route"],
            bool(gt_pmids),
        ),
        "recommended_workflow": dispatch["recommended_workflow"],
        "dispatch_reason": dispatch["dispatch_reason"],
        "nimads_assets": dispatch["nimads_assets"],
        "pmc_assets": dispatch["pmc_assets"],
    }


def load_case_records(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    return read_jsonl(path)


def case_lookup(cases: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for case in cases:
        if case.get("case_id"):
            lookup[str(case["case_id"])] = case
        if case.get("meta_pmid"):
            lookup[str(case["meta_pmid"])] = case
    return lookup
