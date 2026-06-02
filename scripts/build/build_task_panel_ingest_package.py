#!/usr/bin/env python3
"""Build a task-focused ingest package from ONVOC mapping artifacts.

This script consumes outputs from:
1) `gabriel eval-kggen` (for report metadata), and
2) `gabriel map-onvoc` (for ONVOC-mapped rows / edges),

and emits a task-focused package that can be ingested with:

    python -m brain_researcher.cli.main gabriel ingest --manifest <manifest_task_panel.json>
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.services.br_kg.task_family_matcher import TaskFamilyMatcher

DEFAULT_TASK_TAXONOMY_PATH = Path("configs/taxonomy/exports/task_families_master.yaml")
DEFAULT_TASK_ALIAS_EXTENSIONS_PATH = Path(
    "configs/taxonomy/exports/task_family_alias_extensions.yaml"
)
TASK_FOLD_MODES = {"off", "onvoc", "subfamily", "family"}

_TASK_ROUTER_MODALITY_PATTERNS = (
    re.compile(
        r"\b("
        r"fmri|bold|mri|meg|eeg|functional connectivity|connectivity|"
        r"rs ?fmri|resting state|resting-state|neuroimaging|scan|scanning|"
        r"volumetric|voxel|pipeline|preprocessing|processing"
        r")\b",
        re.I,
    ),
)
_TASK_ROUTER_BASELINE_PATTERNS = (
    re.compile(
        r"\b("
        r"baseline|overlap|condition|conditions|contrast|"
        r"contrasts|activation|deactivation|measure|measures|index|indices|"
        r"marker|markers|score|scores|signal|signals|data|dataset|study|studies"
        r")\b",
        re.I,
    ),
)
_TASK_ROUTER_ALLOW_PATTERNS = (
    re.compile(
        r"\b("
        r"localizer|localizers|n back|n-back|"
        r"go no go|go/no-go|gono go|gono-go|stop signal|stroop|flanker|"
        r"iowa gambling|lexical decision|reading|word reading|visual search|"
        r"attentional orienting|"
        r"face processing|face emotion|face name|face-name|familiarity|"
        r"social perception|emotion regulation|reward processing|working memory|"
        r"phonological|semantic|motor task|response inhibition|episodic memory|"
        r"spatial attention|selective attention|sustained attention"
        r")\b",
        re.I,
    ),
)
_TASK_ROUTER_GENERIC_CONSTRUCTS = {
    "attention",
    "emotion",
    "execution",
    "mind",
    "memory",
    "language",
    "cognition",
    "cognitive function",
    "cognitive functions",
    "cognitive performance",
    "motor control",
    "reward responsiveness",
    "cognitive inhibition",
    "selective attention",
    "sustained attention",
    "decision making",
    "motor execution",
}
_TASK_ROUTER_EXACT_CONCEPT_REJECTIONS = _TASK_ROUTER_GENERIC_CONSTRUCTS | {
    "semantic",
    "working memory",
    "social perception",
    "emotion regulation",
}
_TASK_ROUTER_ONVOC_CONTEXT_CUES: dict[str, tuple[str, ...]] = {
    "episodic memory": (
        "episodic memory",
        "verbal episodic memory",
        "memory task",
        "memory tasks",
        "encoding",
        "retrieval",
        "recall",
        "recognition memory",
        "autobiographical memory",
    ),
    "emotion regulation": (
        "emotion regulation",
        "emotion downregulation",
        "cognitive emotion regulation",
        "automatic emotion regulation",
        "emotion regulation strategies",
        "mood regulation",
        "reappraisal",
        "emotion dysregulation",
        "emotional dysregulation",
    ),
}


@dataclass
class FilterResult:
    total: int = 0
    kept: int = 0
    parse_errors: int = 0


@dataclass(frozen=True)
class TaskLaneRoute:
    allow_task_lane: bool
    label_type: str
    reason: str
    input_label: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield raw


def _extract_task_onvoc_ids(crosswalk_payload: dict[str, Any]) -> set[str]:
    task_ids: set[str] = set()
    tasks = crosswalk_payload.get("tasks") or {}
    if not isinstance(tasks, dict):
        return task_ids

    for value in tasks.values():
        if not isinstance(value, dict):
            continue
        primary = str(value.get("primary") or "").strip()
        if primary.startswith("ONVOC_"):
            task_ids.add(primary)
    return task_ids


def _build_source_label_index(mapping_rows_path: Path) -> dict[str, str]:
    source_labels: dict[str, str] = {}
    for raw in _iter_jsonl(mapping_rows_path):
        try:
            row = json.loads(raw)
        except Exception:
            continue
        source_id = str(row.get("source_id") or "").strip()
        source_label = str(row.get("source_label") or "").strip()
        if source_id and source_label and source_id not in source_labels:
            source_labels[source_id] = source_label
    return source_labels


def _normalize_task_route_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _surface_from_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        _, suffix = text.split(":", 1)
    else:
        suffix = text
    return suffix.replace("_", " ").replace("-", " ").strip()


def _resolve_task_route_label(
    row: dict[str, Any],
    *,
    source_labels_by_id: dict[str, str],
) -> str:
    direct_candidates: list[str] = []
    for value in (
        row.get("source_label"),
        (
            (row.get("properties") or {}).get("source_label")
            if isinstance(row.get("properties"), dict)
            else ""
        ),
    ):
        text = str(value or "").strip()
        if text:
            direct_candidates.append(text)
    if direct_candidates:
        return direct_candidates[0]

    target = row.get("target") or {}
    target = target if isinstance(target, dict) else {}
    mapping = row.get("mapping") or {}
    mapping = mapping if isinstance(mapping, dict) else {}
    candidate_ids = [
        str(target.get("original_id") or "").strip(),
        str(mapping.get("original_canonical_id") or "").strip(),
        str(target.get("id") or "").strip(),
        str(mapping.get("canonical_id") or "").strip(),
        str(row.get("source_id") or "").strip(),
    ]
    for candidate_id in candidate_ids:
        if not candidate_id:
            continue
        if candidate_id in source_labels_by_id:
            return source_labels_by_id[candidate_id]
        surface_key = candidate_id.split(":", 1)[-1]
        if surface_key.upper().startswith("ONVOC_"):
            continue
        surfaced = _surface_from_identifier(candidate_id)
        if surfaced:
            return surfaced

    fallback_candidates = [
        str(
            (row.get("normalization") or {}).get("onvoc", {}).get("onvoc_label") or ""
        ).strip(),
        str(target.get("label") or "").strip(),
        str(target.get("name") or "").strip(),
        str(row.get("onvoc_label") or "").strip(),
    ]
    for value in fallback_candidates:
        if value:
            return value
    return ""


def _route_task_lane_candidate(
    *,
    row: dict[str, Any],
    source_labels_by_id: dict[str, str],
    task_matcher: TaskFamilyMatcher | None,
) -> TaskLaneRoute:
    input_label = _resolve_task_route_label(
        row, source_labels_by_id=source_labels_by_id
    )
    normalized = _normalize_task_route_label(input_label)
    onvoc_label = _normalize_task_route_label(
        (row.get("normalization") or {}).get("onvoc", {}).get("onvoc_label")
        or row.get("onvoc_label")
        or (row.get("target") or {}).get("label")
    )
    if not normalized:
        return TaskLaneRoute(
            allow_task_lane=False,
            label_type="unknown",
            reason="missing_input_label",
            input_label=input_label,
        )

    if normalized in _TASK_ROUTER_EXACT_CONCEPT_REJECTIONS:
        return TaskLaneRoute(
            allow_task_lane=False,
            label_type="construct",
            reason="router_generic_construct",
            input_label=input_label,
        )

    for pattern in _TASK_ROUTER_ALLOW_PATTERNS:
        if pattern.search(normalized):
            return TaskLaneRoute(
                allow_task_lane=True,
                label_type="task",
                reason="router_explicit_task_signal",
                input_label=input_label,
            )

    for family_label, cues in _TASK_ROUTER_ONVOC_CONTEXT_CUES.items():
        if onvoc_label != family_label:
            continue
        if any(cue in normalized for cue in cues):
            return TaskLaneRoute(
                allow_task_lane=True,
                label_type="task",
                reason=f"router_onvoc_task_context:{family_label}",
                input_label=input_label,
            )

    for pattern in _TASK_ROUTER_MODALITY_PATTERNS:
        if pattern.search(normalized):
            return TaskLaneRoute(
                allow_task_lane=False,
                label_type="modality_method",
                reason="router_modality_method",
                input_label=input_label,
            )

    for pattern in _TASK_ROUTER_BASELINE_PATTERNS:
        if pattern.search(normalized):
            return TaskLaneRoute(
                allow_task_lane=False,
                label_type="baseline_meta",
                reason="router_baseline_meta",
                input_label=input_label,
            )

    if normalized in _TASK_ROUTER_GENERIC_CONSTRUCTS:
        return TaskLaneRoute(
            allow_task_lane=False,
            label_type="construct",
            reason="router_generic_construct",
            input_label=input_label,
        )

    if task_matcher is not None:
        enriched = task_matcher.enrich_entity(
            {"display_label": input_label, "id": input_label}
        )
        family_id = str(enriched.get("family_id") or "").strip()
        match_method = str(enriched.get("match_method") or "").strip()
        match_score = enriched.get("match_score")
        match_score_value = (
            float(match_score) if isinstance(match_score, int | float) else None
        )
        if family_id and match_method == "exact_alias":
            return TaskLaneRoute(
                allow_task_lane=True,
                label_type="task",
                reason="router_task_family_exact_alias",
                input_label=input_label,
            )
        if (
            family_id
            and match_method == "aggressive_fuzzy_guarded"
            and (match_score_value is None or match_score_value >= 0.9)
        ):
            return TaskLaneRoute(
                allow_task_lane=True,
                label_type="task",
                reason="router_task_family_guarded",
                input_label=input_label,
            )

    return TaskLaneRoute(
        allow_task_lane=False,
        label_type="review_only",
        reason="router_review_only",
        input_label=input_label,
    )


def _edge_onvoc_id(edge: dict[str, Any]) -> str:
    props = edge.get("properties") or {}
    if isinstance(props, dict):
        onvoc_id = str(props.get("onvoc_id") or "").strip()
        if onvoc_id.startswith("ONVOC_"):
            return onvoc_id
    target_id = str(edge.get("target_id") or "").strip()
    if target_id.startswith("concept:ONVOC_"):
        return target_id.split("concept:", 1)[1]
    return ""


def _slugify(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_doi(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    cleaned = text.lower().replace("https://doi.org/", "").replace("doi:", "")
    return cleaned.strip() or None


def _normalize_pmid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = re.sub(r"[^0-9]+", "", text)
    return normalized or None


def _normalize_pmcid(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.lower().replace("pmcid:", "").replace("pmc", "")
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized or None


def _canonical_publication_id(paper: dict[str, Any]) -> str:
    pmid = _normalize_pmid(paper.get("pmid"))
    doi = _normalize_doi(paper.get("doi"))
    pmcid = _normalize_pmcid(paper.get("pmcid"))
    paper_id = _clean_text(paper.get("id"))

    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    if pmcid:
        return f"pmcid:{pmcid}"
    if paper_id:
        if ":" in paper_id:
            return paper_id
        return f"paper:{_slugify(paper_id)}"
    return ""


def _normalize_publication_payload(paper: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(paper)
    original_id = _clean_text(payload.get("id"))
    canonical_id = _canonical_publication_id(payload)
    pmid = _normalize_pmid(payload.get("pmid"))
    doi = _normalize_doi(payload.get("doi"))
    pmcid = _normalize_pmcid(payload.get("pmcid"))

    if canonical_id:
        payload["id"] = canonical_id
    if original_id and canonical_id and original_id != canonical_id:
        payload["original_id"] = original_id
    if pmid:
        payload["pmid"] = pmid
    if doi:
        payload["doi"] = doi
    if pmcid:
        payload["pmcid"] = pmcid
    return payload


def _family_fold_task_id(
    *,
    onvoc_id: str,
    fold_mode: str,
    family_id: str,
    subfamily_id: str,
) -> str:
    if fold_mode == "family" and family_id:
        return f"task:family:{_slugify(family_id)}"
    if fold_mode == "subfamily":
        if subfamily_id:
            return f"task:subfamily:{_slugify(subfamily_id)}"
        if family_id:
            return f"task:family:{_slugify(family_id)}"
    return f"task:onvoc:{onvoc_id.lower()}"


def _match_task_family_from_record(
    *,
    payload: dict[str, Any],
    onvoc_id: str,
    onvoc_label: str,
    task_matcher: TaskFamilyMatcher,
    source_label_override: str = "",
) -> dict[str, Any]:
    """Prefer the original source label before generic ONVOC labels."""

    target = payload.get("target") or {}
    target = target if isinstance(target, dict) else {}
    candidate_labels: list[str] = []
    for value in (
        source_label_override,
        target.get("label"),
        target.get("name"),
        onvoc_label,
    ):
        text = str(value or "").strip()
        if text and text not in candidate_labels:
            candidate_labels.append(text)
    primary_input_label = candidate_labels[0] if candidate_labels else ""

    fallback: dict[str, Any] | None = None
    for label in candidate_labels:
        enriched = task_matcher.enrich_entity(
            {
                "display_label": label,
                "id": onvoc_id,
            }
        )
        if fallback is None:
            fallback = enriched
        if str(enriched.get("family_id") or "").strip():
            enriched["match_input_label"] = primary_input_label or label
            enriched["match_resolved_label"] = label
            return enriched

    if fallback is None:
        fallback = {
            "family_id": None,
            "family_label": None,
            "subfamily_id": None,
            "subfamily_label": None,
            "paradigm_name": None,
            "match_method": "",
            "match_score": None,
        }
    fallback["match_input_label"] = primary_input_label
    fallback["match_resolved_label"] = primary_input_label
    return fallback


def _normalize_task_record(
    record: dict[str, Any],
    onvoc_id: str,
    *,
    task_matcher: TaskFamilyMatcher | None,
    task_fold_mode: str,
    fold_stats: dict[str, int],
    source_label_override: str = "",
) -> dict[str, Any]:
    payload = copy.deepcopy(record)

    norm = payload.get("normalization") or {}
    onvoc = norm.get("onvoc") if isinstance(norm, dict) else {}
    onvoc = onvoc if isinstance(onvoc, dict) else {}

    onvoc_label = str(onvoc.get("onvoc_label") or "").strip()
    onvoc_uri = str(onvoc.get("onvoc_uri") or "").strip()

    base_task_id = f"task:onvoc:{onvoc_id.lower()}"
    task_id = base_task_id
    fold_mode = task_fold_mode if task_fold_mode in TASK_FOLD_MODES else "onvoc"
    family_id = ""
    subfamily_id = ""
    match_method = ""
    match_input_label = ""
    match_resolved_label = ""
    match_score: float | None = None

    if task_matcher is not None and fold_mode in {"subfamily", "family"}:
        enriched = _match_task_family_from_record(
            payload=payload,
            onvoc_id=onvoc_id,
            onvoc_label=onvoc_label,
            task_matcher=task_matcher,
            source_label_override=source_label_override,
        )
        family_id = str(enriched.get("family_id") or "").strip()
        subfamily_id = str(enriched.get("subfamily_id") or "").strip()
        match_method = str(enriched.get("match_method") or "").strip()
        match_input_label = str(enriched.get("match_input_label") or "").strip()
        match_resolved_label = str(enriched.get("match_resolved_label") or "").strip()
        score_raw = enriched.get("match_score")
        match_score = float(score_raw) if isinstance(score_raw, int | float) else None
        if family_id:
            task_id = _family_fold_task_id(
                onvoc_id=onvoc_id,
                fold_mode=fold_mode,
                family_id=family_id,
                subfamily_id=subfamily_id,
            )
            fold_stats["task_records_family_matched"] = (
                fold_stats.get("task_records_family_matched", 0) + 1
            )
            if task_id != base_task_id:
                fold_stats["task_records_folded"] = (
                    fold_stats.get("task_records_folded", 0) + 1
                )
        else:
            fold_stats["task_records_family_unmatched"] = (
                fold_stats.get("task_records_family_unmatched", 0) + 1
            )

    target = payload.setdefault("target", {})
    if not isinstance(target, dict):
        target = {}
        payload["target"] = target
    original_target_id = str(target.get("id") or "").strip()
    target["type"] = "Task"
    target["id"] = task_id
    if onvoc_label:
        target["label"] = onvoc_label
    target["onvoc_id"] = onvoc_id
    if onvoc_uri:
        target["onvoc_uri"] = onvoc_uri
    if original_target_id:
        target["original_id"] = original_target_id

    mapping = payload.setdefault("mapping", {})
    if not isinstance(mapping, dict):
        mapping = {}
        payload["mapping"] = mapping
    mapping["canonical_id"] = task_id
    mapping["mapping_type"] = str(mapping.get("mapping_type") or "synonym")
    mapping["onvoc_id"] = onvoc_id
    if onvoc_uri:
        mapping["onvoc_uri"] = onvoc_uri

    normalization = payload.setdefault("normalization", {})
    if not isinstance(normalization, dict):
        normalization = {}
        payload["normalization"] = normalization
    task_panel_norm: dict[str, Any] = {
        "task_id": task_id,
        "base_task_id": base_task_id,
        "onvoc_id": onvoc_id,
        "source": "kggen_onvoc_task_package",
        "version": "v1",
        "task_fold_mode": fold_mode,
        "packaged_at": _utc_now_iso(),
    }
    if family_id:
        task_panel_norm["family_id"] = family_id
    if subfamily_id:
        task_panel_norm["subfamily_id"] = subfamily_id
    if match_method:
        task_panel_norm["family_match_method"] = match_method
    if match_input_label:
        task_panel_norm["family_match_input_label"] = match_input_label
    if match_resolved_label:
        task_panel_norm["family_match_resolved_label"] = match_resolved_label
    if match_score is not None:
        task_panel_norm["family_match_score"] = match_score
    normalization["task_panel"] = task_panel_norm
    return payload


def _jsonl_filter_transform(
    *,
    input_path: Path,
    output_path: Path,
    keep_fn: Callable[[dict[str, Any]], bool],
    transform_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> FilterResult:
    result = FilterResult()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as writer:
        for raw in _iter_jsonl(input_path):
            result.total += 1
            try:
                row = json.loads(raw)
            except Exception:
                result.parse_errors += 1
                continue
            if not keep_fn(row):
                continue
            out_row = transform_fn(row) if transform_fn is not None else row
            writer.write(json.dumps(out_row, ensure_ascii=True) + "\n")
            result.kept += 1
    return result


def build_task_panel_ingest_package(
    *,
    onvoc_dir: Path,
    output_dir: Path,
    crosswalk_path: Path,
    task_taxonomy_path: Path = DEFAULT_TASK_TAXONOMY_PATH,
    task_alias_extensions_path: Path | None = DEFAULT_TASK_ALIAS_EXTENSIONS_PATH,
    task_fold_mode: str = "subfamily",
    eval_report_path: Path | None = None,
    merge_summary_path: Path | None = None,
) -> dict[str, Any]:
    onvoc_dir = onvoc_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    crosswalk_path = crosswalk_path.expanduser().resolve()
    task_taxonomy_path = task_taxonomy_path.expanduser().resolve()
    resolved_alias_extensions_path: Path | None = None
    if task_alias_extensions_path is not None:
        alias_path = task_alias_extensions_path.expanduser().resolve()
        if alias_path.exists():
            resolved_alias_extensions_path = alias_path
    fold_mode = str(task_fold_mode or "subfamily").strip().lower()
    if fold_mode not in TASK_FOLD_MODES:
        raise ValueError(
            f"Invalid task_fold_mode '{task_fold_mode}'. Expected one of {sorted(TASK_FOLD_MODES)}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    report_onvoc_path = onvoc_dir / "report_onvoc.json"
    mapping_rows_path = onvoc_dir / "mapping_rows.jsonl"
    maps_to_path = onvoc_dir / "edges_maps_to.jsonl"
    same_as_path = onvoc_dir / "edges_same_as.jsonl"
    normalized_path = onvoc_dir / "kggen_normalized_onvoc.jsonl"

    required = [
        report_onvoc_path,
        mapping_rows_path,
        maps_to_path,
        same_as_path,
        normalized_path,
        crosswalk_path,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    task_matcher: TaskFamilyMatcher | None = None
    if fold_mode in {"subfamily", "family"} and task_taxonomy_path.exists():
        matcher = TaskFamilyMatcher(
            taxonomy_path=task_taxonomy_path,
            alias_extensions_path=resolved_alias_extensions_path,
            enable_fuzzy=True,
            aggressive_mode=True,
        )
        if matcher.available:
            task_matcher = matcher

    crosswalk_payload = yaml.safe_load(crosswalk_path.read_text(encoding="utf-8")) or {}
    task_onvoc_ids = _extract_task_onvoc_ids(crosswalk_payload)
    if not task_onvoc_ids:
        raise RuntimeError(f"No task ONVOC IDs found in crosswalk: {crosswalk_path}")

    # Copy source reports for lineage.
    copied_paths: dict[str, str] = {}
    for key, src in [
        ("report_onvoc", report_onvoc_path),
        ("report_eval", eval_report_path),
        ("merge_summary", merge_summary_path),
    ]:
        if src is None:
            continue
        src_resolved = src.expanduser().resolve()
        if not src_resolved.exists():
            continue
        dst = output_dir / src_resolved.name
        shutil.copy2(src_resolved, dst)
        copied_paths[key] = str(dst)

    task_mapping_rows_out = output_dir / "task_panel_mapping_rows.jsonl"
    task_maps_to_out = output_dir / "task_panel_edges_maps_to.jsonl"
    task_same_as_out = output_dir / "task_panel_edges_same_as.jsonl"
    task_records_path = output_dir / "task_panel_records.jsonl"

    task_ids_seen: set[str] = set()
    task_paper_ids: set[str] = set()
    task_ids_canonical: set[str] = set()
    source_labels_by_id = _build_source_label_index(mapping_rows_path)
    fold_stats: dict[str, int] = {
        "task_records_family_matched": 0,
        "task_records_family_unmatched": 0,
        "task_records_folded": 0,
        "publication_ids_canonicalized": 0,
    }
    route_stats: dict[str, int] = {
        "task_router_allowed": 0,
        "task_router_rejected": 0,
    }
    route_reason_counts: dict[str, int] = {}

    def _task_route(row: dict[str, Any]) -> TaskLaneRoute:
        route = _route_task_lane_candidate(
            row=row,
            source_labels_by_id=source_labels_by_id,
            task_matcher=task_matcher,
        )
        bucket = (
            "task_router_allowed" if route.allow_task_lane else "task_router_rejected"
        )
        route_stats[bucket] = route_stats.get(bucket, 0) + 1
        route_reason_counts[route.reason] = route_reason_counts.get(route.reason, 0) + 1
        return route

    mapping_filter = _jsonl_filter_transform(
        input_path=mapping_rows_path,
        output_path=task_mapping_rows_out,
        keep_fn=lambda row: (
            str(row.get("status") or "").strip() == "mapped"
            and str(row.get("onvoc_id") or "").strip() in task_onvoc_ids
            and _task_route(row).allow_task_lane
        ),
    )

    maps_to_filter = _jsonl_filter_transform(
        input_path=maps_to_path,
        output_path=task_maps_to_out,
        keep_fn=lambda row: (
            _edge_onvoc_id(row) in task_onvoc_ids and _task_route(row).allow_task_lane
        ),
    )

    same_as_filter = _jsonl_filter_transform(
        input_path=same_as_path,
        output_path=task_same_as_out,
        keep_fn=lambda row: (
            _edge_onvoc_id(row) in task_onvoc_ids and _task_route(row).allow_task_lane
        ),
    )

    def _keep_normalized(row: dict[str, Any]) -> bool:
        norm = row.get("normalization") or {}
        onvoc = norm.get("onvoc") if isinstance(norm, dict) else {}
        onvoc = onvoc if isinstance(onvoc, dict) else {}
        onvoc_id = str(onvoc.get("onvoc_id") or "").strip()
        if onvoc_id not in task_onvoc_ids:
            return False
        route = _task_route(row)
        return route.allow_task_lane

    def _transform_normalized(row: dict[str, Any]) -> dict[str, Any]:
        norm = row.get("normalization") or {}
        onvoc = norm.get("onvoc") if isinstance(norm, dict) else {}
        onvoc = onvoc if isinstance(onvoc, dict) else {}
        onvoc_id = str(onvoc.get("onvoc_id") or "").strip()
        if onvoc_id:
            task_ids_seen.add(onvoc_id)
        route = _route_task_lane_candidate(
            row=row,
            source_labels_by_id=source_labels_by_id,
            task_matcher=task_matcher,
        )
        target = row.get("target") or {}
        target = target if isinstance(target, dict) else {}
        mapping = row.get("mapping") or {}
        mapping = mapping if isinstance(mapping, dict) else {}
        # Keep family-folding aligned with the same best-effort source label that
        # admitted the row into the task lane in the first place.
        source_label_override = str(route.input_label or "").strip()
        for candidate_id in (
            str(target.get("original_id") or "").strip(),
            str(mapping.get("original_canonical_id") or "").strip(),
        ):
            if source_label_override:
                break
            if candidate_id and candidate_id in source_labels_by_id:
                source_label_override = source_labels_by_id[candidate_id]
                break
        normalized_record = _normalize_task_record(
            row,
            onvoc_id,
            task_matcher=task_matcher,
            task_fold_mode=fold_mode,
            fold_stats=fold_stats,
            source_label_override=source_label_override,
        )
        paper = normalized_record.get("paper") or {}
        if isinstance(paper, dict):
            normalized_paper = _normalize_publication_payload(paper)
            normalized_record["paper"] = normalized_paper
            paper_id = str(normalized_paper.get("id") or "").strip()
            if paper_id:
                task_paper_ids.add(paper_id)
            if str(normalized_paper.get("original_id") or "").strip():
                fold_stats["publication_ids_canonicalized"] = (
                    fold_stats.get("publication_ids_canonicalized", 0) + 1
                )
        target = normalized_record.get("target") or {}
        if isinstance(target, dict):
            task_id = str(target.get("id") or "").strip()
            if task_id:
                task_ids_canonical.add(task_id)
        task_panel_norm = (normalized_record.get("normalization") or {}).get(
            "task_panel"
        ) or {}
        if isinstance(task_panel_norm, dict):
            task_panel_norm["router_label_type"] = route.label_type
            task_panel_norm["router_reason"] = route.reason
            task_panel_norm["router_input_label"] = route.input_label
        return normalized_record

    record_filter = _jsonl_filter_transform(
        input_path=normalized_path,
        output_path=task_records_path,
        keep_fn=_keep_normalized,
        transform_fn=_transform_normalized,
    )

    # Build an ingest-compatible single-shard manifest.
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"gabriel-kggen-task-panel-{run_stamp}"
    shard_dir = output_dir / "shards"
    raw_dir = output_dir / "raw"
    shard_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    shard_path = shard_dir / "shard_0000.jsonl"
    shutil.copy2(task_records_path, shard_path)

    manifest_path = output_dir / "manifest_task_panel.json"
    manifest = {
        "run_id": run_id,
        "created_at": _utc_now_iso(),
        "source": "kggen_onvoc_postprocess",
        "query": "kggen-onvoc-task-panel-package",
        "prompt_template_version": "n/a",
        "generator_version": "kggen-task-panel-package/v1",
        "options": {
            "task_panel_only": True,
            "crosswalk_path": str(crosswalk_path),
            "onvoc_dir": str(onvoc_dir),
            "task_taxonomy_path": str(task_taxonomy_path),
            "task_alias_extensions_path": (
                str(resolved_alias_extensions_path)
                if resolved_alias_extensions_path
                else None
            ),
            "task_fold_mode": fold_mode,
        },
        "source_details": {
            "task_onvoc_ids_total": len(task_onvoc_ids),
            "task_onvoc_ids_seen": len(task_ids_seen),
            "task_ids_canonical_total": len(task_ids_canonical),
        },
        "paths": {
            "run_dir": str(output_dir),
            "shard_dir": str(shard_dir),
            "raw_dir": str(raw_dir),
            "manifest_path": str(manifest_path),
        },
        "counts": {
            "publications_selected": len(task_paper_ids),
            "shards": 1,
            "records_generated": record_filter.kept,
            "records_llm": record_filter.kept,
            "records_heuristic": 0,
            "llm_errors": 0,
            "llm_failure_reasons": {},
        },
        "shards": [
            {
                "shard_id": 0,
                "path": str(shard_path),
                "records_expected": record_filter.kept,
                "records_written": record_filter.kept,
                "mode": "task_panel_onvoc",
            }
        ],
        "ingest": {
            "status": "not_started",
            "started_at": None,
            "completed_at": None,
        },
    }
    _write_json(manifest_path, manifest)

    readme_path = output_dir / "README_task_panel_package.md"
    readme_path.write_text(
        (
            "# KGGEN ONVOC Task Panel Ingest Package\n\n"
            "This package contains task-focused ONVOC-normalized records.\n\n"
            "## Ingest command\n\n"
            "```bash\n"
            "python -m brain_researcher.cli.main gabriel ingest \\\n"
            f"  --manifest {manifest_path} \\\n"
            "  --quality-profile kg_task_panel \\\n"
            "  --create-missing-targets\n"
            "```\n"
        ),
        encoding="utf-8",
    )

    summary = {
        "generated_at": _utc_now_iso(),
        "inputs": {
            "onvoc_dir": str(onvoc_dir),
            "crosswalk_path": str(crosswalk_path),
            "task_taxonomy_path": str(task_taxonomy_path),
            "task_alias_extensions_path": (
                str(resolved_alias_extensions_path)
                if resolved_alias_extensions_path
                else None
            ),
            "task_fold_mode": fold_mode,
            "eval_report_path": str(eval_report_path.expanduser().resolve())
            if eval_report_path
            else None,
            "merge_summary_path": str(merge_summary_path.expanduser().resolve())
            if merge_summary_path
            else None,
        },
        "counts": {
            "task_onvoc_ids_total": len(task_onvoc_ids),
            "task_onvoc_ids_seen_in_records": len(task_ids_seen),
            "task_papers": len(task_paper_ids),
            "task_ids_canonical_total": len(task_ids_canonical),
            "mapping_rows_total": mapping_filter.total,
            "mapping_rows_task_kept": mapping_filter.kept,
            "maps_to_edges_total": maps_to_filter.total,
            "maps_to_edges_task_kept": maps_to_filter.kept,
            "same_as_edges_total": same_as_filter.total,
            "same_as_edges_task_kept": same_as_filter.kept,
            "normalized_records_total": record_filter.total,
            "task_records_kept": record_filter.kept,
            **fold_stats,
            **route_stats,
        },
        "task_router_reason_counts": route_reason_counts,
        "parse_errors": {
            "mapping_rows": mapping_filter.parse_errors,
            "maps_to_edges": maps_to_filter.parse_errors,
            "same_as_edges": same_as_filter.parse_errors,
            "normalized_records": record_filter.parse_errors,
        },
        "artifacts": {
            "manifest_task_panel": str(manifest_path),
            "task_panel_records": str(task_records_path),
            "task_panel_mapping_rows": str(task_mapping_rows_out),
            "task_panel_edges_maps_to": str(task_maps_to_out),
            "task_panel_edges_same_as": str(task_same_as_out),
            "readme": str(readme_path),
            **copied_paths,
        },
    }
    summary_path = output_dir / "package_summary.json"
    _write_json(summary_path, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build task-focused ingest package from ONVOC mapping artifacts."
    )
    parser.add_argument(
        "--onvoc-dir",
        type=Path,
        required=True,
        help="Directory produced by `gabriel map-onvoc`.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for task panel package.",
    )
    parser.add_argument(
        "--crosswalk-path",
        type=Path,
        default=Path("configs/legacy/mappings/onvoc_crosswalk.yaml"),
        help="ONVOC crosswalk path (for task ONVOC IDs).",
    )
    parser.add_argument(
        "--task-taxonomy-path",
        type=Path,
        default=DEFAULT_TASK_TAXONOMY_PATH,
        help="Task taxonomy YAML used for family/subfamily folding.",
    )
    parser.add_argument(
        "--task-alias-extensions-path",
        type=Path,
        default=DEFAULT_TASK_ALIAS_EXTENSIONS_PATH,
        help="Optional task-family alias-extension YAML used during family/subfamily folding.",
    )
    parser.add_argument(
        "--task-fold-mode",
        type=str,
        choices=sorted(TASK_FOLD_MODES),
        default="subfamily",
        help="Canonical task ID fold mode: off|onvoc|subfamily|family.",
    )
    parser.add_argument(
        "--eval-report",
        type=Path,
        default=None,
        help="Optional eval-kggen report.json path to copy into package.",
    )
    parser.add_argument(
        "--merge-summary",
        type=Path,
        default=None,
        help="Optional merge summary path to copy into package.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print package summary as JSON.",
    )
    args = parser.parse_args()

    summary = build_task_panel_ingest_package(
        onvoc_dir=args.onvoc_dir,
        output_dir=args.output_dir,
        crosswalk_path=args.crosswalk_path,
        task_taxonomy_path=args.task_taxonomy_path,
        task_alias_extensions_path=args.task_alias_extensions_path,
        task_fold_mode=args.task_fold_mode,
        eval_report_path=args.eval_report,
        merge_summary_path=args.merge_summary,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=True, indent=2))
    else:
        print("Task panel ingest package complete")
        print(f"Manifest: {summary['artifacts']['manifest_task_panel']}")
        print(f"Task records: {summary['artifacts']['task_panel_records']}")
        print(
            f"Summary: {Path(summary['artifacts']['manifest_task_panel']).parent / 'package_summary.json'}"
        )


if __name__ == "__main__":
    main()
