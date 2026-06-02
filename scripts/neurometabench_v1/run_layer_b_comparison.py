#!/usr/bin/env python3
"""Compare existing NeuroMetaBench Layer B reproduction artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUMMARY_FILENAMES = {
    "summary.json",
    "RUN_SUMMARY.json",
    "path_b_reproduction_summary.json",
}
CASE_DIR_RE = re.compile(r"^layer_b_(?P<pmid>\d+)(?:_(?P<slug>.+))?$")
DEFAULT_CASES_PATH = Path("benchmarks/neurometabench/cases.v1.jsonl")
STATUS_VALUES_FAILED = {"error", "errored", "fail", "failed", "failure"}
PROVENANCE_REQUIRED_FIELDS = (
    ("condition_id",),
    ("runner",),
    ("model_target",),
    ("br_mode",),
    ("source_assets_used", "source_assets", "inputs"),
    ("commands_executed", "commands"),
    ("start_timestamp", "start_at", "started_at"),
    ("end_timestamp", "end_at", "ended_at"),
    ("repository_commit",),
)
PUBLIC_STUDY_ID_FIELDS = ("pmid", "study_pmid", "doi", "pmcid")
LOCAL_STUDY_ID_FIELDS = ("study_id", "study_name", "original_study_ids", "study_match_key")
LOCAL_STUDY_PRIMARY_FIELDS = (
    "study_match_key",
    "study_id",
    "study_pmid",
    "pmid",
    "doi",
    "pmcid",
    "study_name",
)
LOCAL_STUDY_FALLBACK_FIELDS = ("original_study_ids", "source_study_ids")
PMID_LIKE_STUDY_ID_FIELDS = ("study_id", "original_study_ids", "source_study_ids")
SOURCE_PROVENANCE_FIELDS = (
    "source_asset",
    "source_project",
    "source_json",
    "source_file",
    "source",
    "original_study_ids",
    "original_study_ids_by_source",
    "source_study_ids",
)
SAMPLE_SIZE_FIELDS = (
    "sample_sizes",
    "sample_size",
    "sample_size_min",
    "sample_size_max",
    "sample_size_mean",
    "n",
    "n_subjects",
    "participants",
)
COORDINATE_ANALYSIS_FIELDS = ("analysis_id", "analysis_name", "contrast_id")
COORDINATE_STUDY_FIELDS = ("study_id", "study_name", "study", "study_label", "article_id")
COORDINATE_SPACE_FIELDS = ("space", "source_space", "coordinate_space", "coord_space")
COORDINATE_X_FIELDS = ("x", "X", "coord_x")
COORDINATE_Y_FIELDS = ("y", "Y", "coord_y")
COORDINATE_Z_FIELDS = ("z", "Z", "coord_z")
MAP_ROLE_ORDER = ("z", "stat", "p")
PMID_TOKEN_RE = re.compile(r"\b\d{6,9}\b")
GENERIC_LOCAL_STUDY_IDS = {"", "study", "studies", "unknown", "na", "n/a", "none", "null"}
GENERIC_ANALYSIS_ID_RE = re.compile(r"analysis[_\s-]*\d+$", re.IGNORECASE)
SPATIAL_EQUIVALENCE_CORRELATION = 0.999
SPATIAL_EQUIVALENCE_DICE = 0.99
FALLBACK_MAP_TERMS = (
    "synthetic ale",
    "synthetic map",
    "degraded_fallback",
    "degraded fallback",
    "gaussian kde",
    "gaussian kernel density",
    "kernel density approximation",
    "approximate ale",
    "nimare ale failed",
    "nimare fallback",
    "fell back to gaussian",
    "fallback gaussian",
    "hand-rolled ale",
    "tuple index out of range",
)
FALLBACK_SCAN_SKIP_JSON_KEYS = {
    "argv",
    "cmd",
    "command",
    "commands",
    "commands_executed",
    "full_prompt",
    "input_prompt",
    "instructions",
    "model_prompt",
    "prompt",
    "prompts",
    "raw_prompt",
    "system_prompt",
    "user_prompt",
}
FALLBACK_STRUCTURED_FLAG_FIELDS = {
    "degraded_fallback_map",
    "fallback_map_generated",
    "synthetic_map_generated",
}
FALLBACK_STRUCTURED_STATUS_FIELDS = {
    "ale_map_generation_status",
    "map_generation_status",
    "map_status",
}
FALLBACK_TRUE_STATUS_VALUES = {
    "degraded_fallback",
    "fallback",
    "fallback_map",
    "gaussian_kde_fallback",
    "synthetic",
    "synthetic_ale",
    "synthetic_map",
}
FALLBACK_FALSE_STATUS_VALUES = {
    "clean",
    "generated",
    "generated_nimare_ale",
    "nimare_ale",
    "nimare_ale_generated",
    "not_degraded_fallback",
    "ok",
    "official_nimare_ale",
    "success",
    "succeeded",
}
FALSE_LITERAL_RE = r"[`'\"\s]*(?:false|no|0)[`'\"\s.,;]*"
NONFALLBACK_STATUS_LITERAL_RE = (
    r"[`'\"\s]*(?:"
    + "|".join(sorted(re.escape(value) for value in FALLBACK_FALSE_STATUS_VALUES))
    + r")[`'\"\s.,;]*"
)


@dataclass(frozen=True)
class ConditionInput:
    name: str
    path: Path


@dataclass(frozen=True)
class DiscoveredCase:
    condition: str
    condition_path: Path
    data: dict[str, Any]
    source_file: Path
    source_kind: str
    case_dir: Path
    source_rank: int


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_summary_candidate(path: Path) -> bool:
    name = path.name
    lower = name.lower()
    return (
        name in SUMMARY_FILENAMES
        or lower in {entry.lower() for entry in SUMMARY_FILENAMES}
        or (lower.endswith("_summary.json") and ("layer_b" in lower or "path_b" in lower))
    )


def _looks_like_case_metrics(data: dict[str, Any], path: Path) -> bool:
    if path.name == "metrics.json" and path.parent.name.startswith("layer_b_"):
        return True
    return any(
        key in data
        for key in (
            "ale",
            "case_id",
            "map_generated",
            "meta_pmid",
            "n_coordinate_rows",
            "n_included_studies",
            "n_nimads_studies",
            "outputs",
            "split_half",
        )
    )


def _path_after_named_part(path: Path, part: str) -> Path | None:
    parts = path.parts
    if part not in parts:
        return None
    index = len(parts) - 1 - list(reversed(parts)).index(part)
    suffix_parts = parts[index + 1 :]
    if not suffix_parts:
        return Path()
    return Path(*suffix_parts)


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_existing_path(
    value: Any,
    *,
    case_dir: Path,
    condition_path: Path,
) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    raw = Path(value)
    candidates: list[Path] = []
    if not raw.is_absolute():
        candidates.extend([case_dir / raw, condition_path / raw])

    for base in (case_dir, condition_path):
        suffix = _path_after_named_part(raw, base.name)
        if suffix is not None:
            candidates.append(base / suffix)

    if raw.name:
        candidates.extend(sorted(case_dir.rglob(raw.name)))
        candidates.extend(sorted(condition_path.rglob(raw.name)))
    if raw.is_absolute():
        candidates.append(raw)
    return _first_existing_path(candidates)


def _resolve_output_dir(
    value: Any,
    *,
    source_file: Path,
    condition_path: Path,
    meta_pmid: str | None,
) -> Path:
    if source_file.parent.name.startswith("layer_b_"):
        return source_file.parent

    if isinstance(value, str) and value:
        raw = Path(value)
        candidates: list[Path] = []
        if not raw.is_absolute():
            candidates.extend([condition_path / raw, source_file.parent / raw])
        if raw.name:
            candidates.extend(
                candidate
                for candidate in sorted(condition_path.rglob(raw.name))
                if candidate.is_dir()
            )
        if raw.is_absolute():
            candidates.append(raw)
        existing = _first_existing_path(candidates)
        if existing and existing.is_dir():
            return existing

    if meta_pmid:
        matches = sorted(
            candidate
            for candidate in condition_path.rglob(f"layer_b_{meta_pmid}*")
            if candidate.is_dir()
        )
        if matches:
            return matches[0]
    return source_file.parent


def _nested_get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _meta_pmid_from_path(path: Path) -> str | None:
    for parent in [path.parent, *path.parents]:
        match = CASE_DIR_RE.match(parent.name)
        if match:
            return match.group("pmid")
    return None


def _case_identity(data: dict[str, Any], source_file: Path) -> tuple[str | None, str | None]:
    case_id = _string_or_none(data.get("case_id") or data.get("id"))
    meta_pmid = _string_or_none(
        data.get("meta_pmid")
        or data.get("pmid")
        or data.get("case_pmid")
        or _nested_get(data, ("case", "meta_pmid"))
    )
    if not meta_pmid and case_id and ":" in case_id:
        possible = case_id.rsplit(":", maxsplit=1)[-1]
        if possible.isdigit():
            meta_pmid = possible
    if not meta_pmid:
        meta_pmid = _meta_pmid_from_path(source_file)
    if case_id and case_id.isdigit():
        meta_pmid = meta_pmid or case_id
        case_id = f"neurometabench:{case_id}"
    if not case_id and meta_pmid:
        case_id = f"neurometabench:{meta_pmid}"
    return case_id, meta_pmid


def _case_key(data: dict[str, Any], source_file: Path, case_dir: Path) -> str:
    case_id, meta_pmid = _case_identity(data, source_file)
    if case_id:
        return case_id
    if meta_pmid:
        return f"pmid:{meta_pmid}"
    return str(case_dir)


def _discover_from_file(
    condition: ConditionInput,
    path: Path,
) -> list[DiscoveredCase]:
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        failed_data = {
            "status": "failed",
            "error": f"unreadable_json: {exc}",
        }
        return [
            DiscoveredCase(
                condition=condition.name,
                condition_path=condition.path,
                data=failed_data,
                source_file=path,
                source_kind="unreadable_json",
                case_dir=path.parent,
                source_rank=0,
            )
        ]

    if not isinstance(data, dict):
        return []

    case_rows = data.get("cases")
    if not isinstance(case_rows, list):
        case_rows = _nested_get(data, ("summary", "cases"))
    if isinstance(case_rows, list):
        discovered: list[DiscoveredCase] = []
        for row in case_rows:
            if not isinstance(row, dict):
                continue
            _case_id, meta_pmid = _case_identity(row, path)
            case_dir = _resolve_output_dir(
                _nested_get(row, ("outputs", "output_dir")) or row.get("output_dir"),
                source_file=path,
                condition_path=condition.path,
                meta_pmid=meta_pmid,
            )
            discovered.append(
                DiscoveredCase(
                    condition=condition.name,
                    condition_path=condition.path,
                    data=row,
                    source_file=path,
                    source_kind=path.name,
                    case_dir=case_dir,
                    source_rank=2,
                )
            )
        return discovered

    if path.name == "metrics.json" or _looks_like_case_metrics(data, path):
        _case_id, meta_pmid = _case_identity(data, path)
        case_dir = _resolve_output_dir(
            _nested_get(data, ("outputs", "output_dir")) or data.get("output_dir"),
            source_file=path,
            condition_path=condition.path,
            meta_pmid=meta_pmid,
        )
        return [
            DiscoveredCase(
                condition=condition.name,
                condition_path=condition.path,
                data=data,
                source_file=path,
                source_kind=path.name,
                case_dir=case_dir,
                source_rank=3 if path.name == "metrics.json" else 1,
            )
        ]
    return []


def discover_cases(condition: ConditionInput) -> list[DiscoveredCase]:
    paths = []
    for path in sorted(condition.path.rglob("*.json")):
        if path.name == "metrics.json" or _is_summary_candidate(path):
            paths.append(path)

    by_key: dict[str, DiscoveredCase] = {}
    for path in paths:
        for discovered in _discover_from_file(condition, path):
            key = _case_key(discovered.data, discovered.source_file, discovered.case_dir)
            current = by_key.get(key)
            if current is None or discovered.source_rank > current.source_rank:
                by_key[key] = discovered
    return sorted(
        by_key.values(),
        key=lambda case: _case_key(case.data, case.source_file, case.case_dir),
    )


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _count_csv_rows(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def _read_csv_rows(path: Path | None) -> tuple[list[str], list[dict[str, str]]]:
    if path is None or not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _row_has_any(row: dict[str, str], fields: tuple[str, ...]) -> bool:
    return any((row.get(field) or "").strip() for field in fields)


def _coverage(rows: list[dict[str, str]], fields: tuple[str, ...]) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if _row_has_any(row, fields)) / len(rows)


def _first_row_value(row: dict[str, str], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return None


def _pmid_like_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return set(PMID_TOKEN_RE.findall(value))


def _row_has_public_study_identifier(row: dict[str, str]) -> bool:
    if _row_has_any(row, PUBLIC_STUDY_ID_FIELDS):
        return True
    return any(
        _pmid_like_tokens(row.get(field))
        for field in PMID_LIKE_STUDY_ID_FIELDS
    )


def _public_study_identifier_coverage(rows: list[dict[str, str]]) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if _row_has_public_study_identifier(row)) / len(rows)


def _as_float_text(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return f"{number:.3f}"


def _coordinate_space_signature(value: str | None) -> str:
    if value is None:
        return ""
    text = value.strip()
    normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
    if normalized in {
        "mni",
        "mnispace",
        "mni152",
        "mni1522mm",
        "mni1521mm",
        "mni152nlin6",
        "mni152nlin6asym",
        "mni152nlin2009casym",
    }:
        return "MNI"
    if normalized in {"tal", "talairach", "talairachspace"}:
        return "TAL"
    return text


def _metric_value(value: Any, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "reason": reason}


def _load_json_dict(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _normalize_structured_token(value: Any) -> str:
    text = str(value).strip().strip("`'\"").lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = _normalize_structured_token(value)
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0", "none", "null"}:
            return False
    return None


def _iter_structured_scalars(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        items: list[tuple[tuple[str, ...], Any]] = []
        for key, item in value.items():
            items.extend(_iter_structured_scalars(item, path + (str(key),)))
        return items
    if isinstance(value, list):
        items = []
        for index, item in enumerate(value):
            items.extend(_iter_structured_scalars(item, path + (str(index),)))
        return items
    return [(path, value)]


def _structured_fallback_map_decision(data: dict[str, Any]) -> dict[str, Any] | None:
    fallback_terms: set[str] = set()
    nonfallback_terms: set[str] = set()

    for path, value in _iter_structured_scalars(data):
        if not path:
            continue
        raw_key = path[-1]
        key = _normalize_structured_token(raw_key)
        path_label = ".".join(path)
        if key in FALLBACK_STRUCTURED_FLAG_FIELDS:
            parsed = _coerce_bool(value)
            if parsed is True:
                fallback_terms.add(f"{path_label}=true")
            elif parsed is False:
                nonfallback_terms.add(f"{path_label}=false")
        elif key in FALLBACK_STRUCTURED_STATUS_FIELDS:
            status = _normalize_structured_token(value)
            if status in FALLBACK_TRUE_STATUS_VALUES:
                fallback_terms.add(f"{path_label}={value}")
            elif status in FALLBACK_FALSE_STATUS_VALUES:
                nonfallback_terms.add(f"{path_label}={value}")

    if fallback_terms:
        return {"detected": True, "terms": sorted(fallback_terms), "kind": "structured"}
    if nonfallback_terms:
        return {
            "detected": False,
            "terms": sorted(nonfallback_terms),
            "kind": "structured",
        }
    return None


def _fallback_term_pattern(term: str) -> str:
    parts = [part for part in re.split(r"[_\s-]+", term) if part]
    return r"[_\s-]+".join(re.escape(part) for part in parts)


def _remove_nonfallback_markers(line: str) -> str:
    cleaned = re.sub(
        r"[\"']?\bale_map_not_degraded_fallback\b[\"']?",
        "",
        line,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"[\"']?\bdegraded[_\s-]*fallback(?:[_\s-]*map)?\b[\"']?\s*[:=]\s*"
        + FALSE_LITERAL_RE,
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"[\"']?\bfallback[_\s-]*map[_\s-]*generated\b[\"']?\s*[:=]\s*"
        + FALSE_LITERAL_RE,
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"[\"']?\bmap[_\s-]*generation[_\s-]*status\b[\"']?\s*[:=]\s*"
        + NONFALLBACK_STATUS_LITERAL_RE,
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    for term in FALLBACK_MAP_TERMS:
        cleaned = re.sub(
            r"\b(?:no|not|without|non)\s+(?:a\s+|an\s+|any\s+)?"
            + _fallback_term_pattern(term),
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _fallback_map_terms(text: str) -> list[str]:
    matches: set[str] = set()
    for line in text.splitlines() or [text]:
        lower = _remove_nonfallback_markers(line).lower()
        for term in FALLBACK_MAP_TERMS:
            pattern = rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])"
            if re.search(pattern, lower):
                matches.add(term)
    return sorted(matches)


def _scrub_promptish_json_for_fallback_scan(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if (
                normalized_key in FALLBACK_SCAN_SKIP_JSON_KEYS
                or "prompt" in normalized_key
                or "instruction" in normalized_key
            ):
                continue
            scrubbed[key] = _scrub_promptish_json_for_fallback_scan(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_promptish_json_for_fallback_scan(item) for item in value]
    return value


def _fallback_scan_text_for_json_file(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _read_text(path)
    scrubbed = _scrub_promptish_json_for_fallback_scan(data)
    return json.dumps(scrubbed, ensure_ascii=False, sort_keys=True)


def _fallback_map_evidence(case: DiscoveredCase) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    nonfallback_sources: list[dict[str, Any]] = []
    source_texts: list[tuple[str, str]] = []
    case_decision = _structured_fallback_map_decision(case.data)
    if case_decision is not None:
        entry = {
            "source": str(case.source_file),
            "terms": case_decision["terms"],
            "kind": "structured",
        }
        if case_decision["detected"]:
            matches.append(entry)
        else:
            nonfallback_sources.append(entry)
    else:
        source_texts.append(
            (
                str(case.source_file),
                json.dumps(
                    _scrub_promptish_json_for_fallback_scan(case.data),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    for name in (
        "metrics.json",
        "provenance_manifest.json",
        "spatial_report.md",
        "trajectory.json",
        "observation.json",
        "failure.json",
        "RUN_SUMMARY.json",
    ):
        path = case.case_dir / name
        if name in {"metrics.json", "provenance_manifest.json"}:
            data = _load_json_dict(path)
            decision = _structured_fallback_map_decision(data) if data else None
            if decision is not None:
                entry = {"source": str(path), "terms": decision["terms"], "kind": "structured"}
                if decision["detected"]:
                    matches.append(entry)
                else:
                    nonfallback_sources.append(entry)
                continue
        text = _fallback_scan_text_for_json_file(path) if name.endswith(".json") else _read_text(path)
        if text:
            source_texts.append((str(path), text))

    seen: set[tuple[str, tuple[str, ...]]] = set()
    for source, text in source_texts:
        terms = _fallback_map_terms(text)
        if not terms:
            continue
        key = (source, tuple(terms))
        if key in seen:
            continue
        seen.add(key)
        matches.append({"source": source, "terms": terms})

    detected = bool(matches)
    return {
        "pass": not detected,
        "detected": detected,
        "reason": "degraded_fallback_map_evidence" if detected else None,
        "matches": matches,
        "structured_nonfallback": nonfallback_sources,
    }


def _has_any_key(data: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return True
    return False


def _mean(values: list[float | int | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def _rate(values: list[bool | None]) -> float | None:
    observed = [value for value in values if value is not None]
    if not observed:
        return None
    return sum(1 for value in observed if value) / len(observed)


def _metric_mean(values: list[dict[str, Any] | None]) -> float | None:
    return _mean(
        [
            value.get("value")
            for value in values
            if isinstance(value, dict)
            and isinstance(value.get("value"), (int, float))
            and not isinstance(value.get("value"), bool)
        ]
    )


def _load_case_gold_pmids(cases_path: Path) -> dict[str, set[str]]:
    if not cases_path.exists():
        return {}
    gold: dict[str, set[str]] = {}
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        meta_pmid = str(row.get("meta_pmid") or "").strip()
        if not meta_pmid:
            continue
        pmids = {
            str(pmid).strip()
            for pmid in row.get("gt_pmids", [])
            if str(pmid).strip()
        }
        gold[meta_pmid] = pmids
    return gold


def _extract_public_study_ids(included_studies_path: Path | None) -> set[str]:
    _fields, rows = _read_csv_rows(included_studies_path)
    public_ids: set[str] = set()
    for row in rows:
        for field in ("pmid", "study_pmid"):
            value = (row.get(field) or "").strip()
            if value:
                public_ids.add(value)
        for field in PMID_LIKE_STUDY_ID_FIELDS:
            public_ids.update(_pmid_like_tokens(row.get(field)))
    return public_ids


def _split_identifier_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token.strip().strip("[]\"'")
        for token in re.split(r"[|,;\s]+", value)
        if token.strip().strip("[]\"'")
    }


def _canonical_identifier_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.strip().strip("[]\"'"))


def _first_identifier_token(value: str | None) -> str:
    tokens = _split_identifier_tokens(value)
    return sorted(tokens, key=str)[0] if tokens else ""


def _row_primary_local_study_id(row: dict[str, str]) -> str:
    generic_candidate = ""
    for field in LOCAL_STUDY_PRIMARY_FIELDS:
        value = _canonical_identifier_text(row.get(field))
        if not value:
            continue
        normalized = value.lower()
        if normalized in GENERIC_LOCAL_STUDY_IDS:
            generic_candidate = generic_candidate or value
            continue
        return value
    for field in LOCAL_STUDY_FALLBACK_FIELDS:
        value = _first_identifier_token(row.get(field))
        if value:
            return value
    return generic_candidate


def _extract_local_study_ids(included_studies_path: Path | None) -> set[str]:
    _fields, rows = _read_csv_rows(included_studies_path)
    local_ids: set[str] = set()
    for row in rows:
        key = _row_primary_local_study_id(row)
        if key:
            local_ids.add(key)
    return local_ids


def _precision_recall_f1(
    *,
    predicted: set[str],
    gold: set[str],
) -> dict[str, Any]:
    if not gold:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "n_pred": len(predicted),
            "n_gold": 0,
            "n_tp": 0,
            "reason": "missing_pmid_level_gold",
        }
    if not predicted:
        return {
            "precision": None,
            "recall": 0.0,
            "f1": None,
            "n_pred": 0,
            "n_gold": len(gold),
            "n_tp": 0,
            "reason": "missing_public_study_identifiers",
        }
    n_tp = len(predicted & gold)
    precision = n_tp / len(predicted) if predicted else None
    recall = n_tp / len(gold) if gold else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "n_pred": len(predicted),
        "n_gold": len(gold),
        "n_tp": n_tp,
        "reason": None,
    }


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_generic_analysis_id(value: str) -> bool:
    text = value.strip().lower()
    return text in GENERIC_LOCAL_STUDY_IDS or bool(GENERIC_ANALYSIS_ID_RE.fullmatch(text))


def _coordinate_study_key(row: dict[str, str]) -> str:
    study = _canonical_identifier_text(_first_row_value(row, COORDINATE_STUDY_FIELDS))
    analysis = _canonical_identifier_text(_first_row_value(row, COORDINATE_ANALYSIS_FIELDS))
    if study.lower() in GENERIC_LOCAL_STUDY_IDS and analysis:
        return analysis
    return study


def _coordinate_analysis_key(row: dict[str, str], *, study_key: str) -> str:
    analysis = _canonical_identifier_text(_first_row_value(row, COORDINATE_ANALYSIS_FIELDS))
    if not analysis or analysis == study_key or _is_generic_analysis_id(analysis):
        return ""
    return analysis


def _coordinate_signature(
    row: dict[str, str],
    *,
    include_identifiers: bool = True,
) -> tuple[str, ...] | None:
    x = _as_float_text(_first_row_value(row, COORDINATE_X_FIELDS))
    y = _as_float_text(_first_row_value(row, COORDINATE_Y_FIELDS))
    z = _as_float_text(_first_row_value(row, COORDINATE_Z_FIELDS))
    if x is None or y is None or z is None:
        return None
    coordinate = (
        x,
        y,
        z,
        _coordinate_space_signature(_first_row_value(row, COORDINATE_SPACE_FIELDS)),
    )
    if not include_identifiers:
        return coordinate
    study_key = _coordinate_study_key(row)
    return (
        study_key,
        _coordinate_analysis_key(row, study_key=study_key),
        *coordinate,
    )


def _coordinate_counter(
    path: Path | None,
    *,
    include_identifiers: bool = True,
) -> Counter[tuple[str, ...]]:
    _fields, rows = _read_csv_rows(path)
    counter: Counter[tuple[str, ...]] = Counter()
    for row in rows:
        signature = _coordinate_signature(row, include_identifiers=include_identifiers)
        if signature is not None:
            counter[signature] += 1
    return counter


def _counter_overlap(a: Counter[tuple[str, ...]], b: Counter[tuple[str, ...]]) -> int:
    return sum((a & b).values())


def _coordinate_agreement(
    *,
    case_path: Path | None,
    control_path: Path | None,
    include_identifiers: bool = True,
) -> dict[str, Any]:
    if case_path is None or control_path is None:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": "missing_coordinate_table",
        }
    case_counter = _coordinate_counter(case_path, include_identifiers=include_identifiers)
    control_counter = _coordinate_counter(
        control_path,
        include_identifiers=include_identifiers,
    )
    if not case_counter or not control_counter:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": "missing_parseable_coordinates",
        }
    n_overlap = _counter_overlap(case_counter, control_counter)
    n_case = sum(case_counter.values())
    n_control = sum(control_counter.values())
    precision = n_overlap / n_case if n_case else None
    recall = n_overlap / n_control if n_control else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "n_overlap": n_overlap,
        "n_case": n_case,
        "n_control": n_control,
        "reason": None,
    }


def _spatial_maps_equivalent(spatial_agreement: dict[str, Any]) -> bool:
    correlation = spatial_agreement.get("spatial_correlation")
    dice = spatial_agreement.get("dice_top5")
    return (
        isinstance(correlation, (int, float))
        and isinstance(dice, (int, float))
        and correlation >= SPATIAL_EQUIVALENCE_CORRELATION
        and dice >= SPATIAL_EQUIVALENCE_DICE
    )


def _spatial_equivalent_coordinate_agreement(
    agreement: dict[str, Any],
    *,
    spatial_agreement: dict[str, Any],
) -> dict[str, Any]:
    n_case = agreement.get("n_case")
    n_control = agreement.get("n_control")
    if (
        agreement.get("f1") == 1.0
        or not _spatial_maps_equivalent(spatial_agreement)
        or not isinstance(n_case, int)
        or not isinstance(n_control, int)
        or n_case != n_control
    ):
        return agreement
    updated = dict(agreement)
    updated.update(
        {
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "n_overlap": n_case,
            "raw_precision": agreement.get("precision"),
            "raw_recall": agreement.get("recall"),
            "raw_f1": agreement.get("f1"),
            "raw_n_overlap": agreement.get("n_overlap"),
            "reason": "spatial_map_equivalent_after_coordinate_transform",
        }
    )
    return updated


def _set_f1(
    *,
    predicted: set[str],
    gold: set[str],
    missing_reason: str,
) -> dict[str, Any]:
    if not gold:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "n_pred": len(predicted),
            "n_gold": 0,
            "n_tp": 0,
            "reason": missing_reason,
        }
    if not predicted:
        return {
            "precision": None,
            "recall": 0.0,
            "f1": None,
            "n_pred": 0,
            "n_gold": len(gold),
            "n_tp": 0,
            "reason": "missing_predicted_identifiers",
        }
    n_tp = len(predicted & gold)
    precision = n_tp / len(predicted) if predicted else None
    recall = n_tp / len(gold) if gold else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "n_pred": len(predicted),
        "n_gold": len(gold),
        "n_tp": n_tp,
        "reason": None,
    }


def _local_study_set_agreement(
    *,
    case_path: Path | None,
    control_path: Path | None,
) -> dict[str, Any]:
    if case_path is None or control_path is None:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "n_pred": 0,
            "n_gold": 0,
            "n_tp": 0,
            "reason": "missing_included_studies_table",
        }
    return _set_f1(
        predicted=_extract_local_study_ids(case_path),
        gold=_extract_local_study_ids(control_path),
        missing_reason="missing_control_local_study_identifiers",
    )


def _map_role(path: Path) -> str:
    name = path.name.lower()
    for role in MAP_ROLE_ORDER:
        if f"_{role}.nii" in name or name.startswith(f"{role}.nii"):
            return role
    return path.name


def _map_paths_by_role(paths: list[str]) -> dict[str, Path]:
    by_role: dict[str, Path] = {}
    for raw_path in paths:
        path = Path(raw_path)
        by_role.setdefault(_map_role(path), path)
    return by_role


def _load_map_data(path: Path) -> Any:
    import nibabel as nib
    import numpy as np

    data = nib.load(str(path)).get_fdata()
    return np.asarray(data, dtype=float)


def _spatial_map_agreement(
    *,
    case_paths: list[str],
    control_paths: list[str],
) -> dict[str, Any]:
    case_maps = _map_paths_by_role(case_paths)
    control_maps = _map_paths_by_role(control_paths)
    role = "z" if "z" in case_maps and "z" in control_maps else None
    if role is None:
        common_roles = [candidate for candidate in MAP_ROLE_ORDER if candidate in case_maps and candidate in control_maps]
        role = common_roles[0] if common_roles else None
    if role is None:
        return {
            "map_role": None,
            "spatial_correlation": None,
            "dice_top5": None,
            "reason": "missing_comparable_map",
        }
    try:
        import numpy as np

        case_data = _load_map_data(case_maps[role])
        control_data = _load_map_data(control_maps[role])
    except Exception as exc:  # pragma: no cover - depends on optional NIfTI stack
        return {
            "map_role": role,
            "spatial_correlation": None,
            "dice_top5": None,
            "reason": f"map_load_failed:{type(exc).__name__}",
        }
    if case_data.shape != control_data.shape:
        return {
            "map_role": role,
            "spatial_correlation": None,
            "dice_top5": None,
            "reason": "map_shape_mismatch",
        }
    finite = np.isfinite(case_data) & np.isfinite(control_data)
    if finite.sum() < 2:
        return {
            "map_role": role,
            "spatial_correlation": None,
            "dice_top5": None,
            "reason": "too_few_finite_voxels",
        }
    case_values = case_data[finite].ravel()
    control_values = control_data[finite].ravel()
    if float(np.std(case_values)) == 0.0 or float(np.std(control_values)) == 0.0:
        correlation = None
        reason = "zero_variance_map"
    else:
        correlation = float(np.corrcoef(case_values, control_values)[0, 1])
        reason = None

    positive = finite & ((case_data > 0) | (control_data > 0))
    if positive.sum() == 0:
        return {
            "map_role": role,
            "spatial_correlation": correlation,
            "dice_top5": None,
            "reason": reason or "no_positive_voxels",
        }
    n_top = max(1, int(math.ceil(float(positive.sum()) * 0.05)))
    case_positive = case_data[positive].ravel()
    control_positive = control_data[positive].ravel()
    case_threshold = np.partition(case_positive, -n_top)[-n_top]
    control_threshold = np.partition(control_positive, -n_top)[-n_top]
    case_top = positive & (case_data >= case_threshold)
    control_top = positive & (control_data >= control_threshold)
    denominator = int(case_top.sum() + control_top.sum())
    dice = (
        2 * int((case_top & control_top).sum()) / denominator
        if denominator
        else None
    )
    return {
        "map_role": role,
        "spatial_correlation": correlation,
        "dice_top5": dice,
        "reason": reason,
    }


def _artifact_presence(
    *,
    label: str,
    declared_path: Any,
    fallback_paths: list[Path],
    case_dir: Path,
    condition_path: Path,
) -> dict[str, Any]:
    resolved = _resolve_existing_path(
        declared_path,
        case_dir=case_dir,
        condition_path=condition_path,
    )
    if resolved is None:
        resolved = _first_existing_path(fallback_paths)
    return {
        "present": resolved is not None,
        "path": str(resolved) if resolved else None,
        "declared_path": declared_path if isinstance(declared_path, str) else None,
        "label": label,
    }


def _study_reconciliation_metrics(included_studies_path: Path | None) -> dict[str, Any]:
    fields, rows = _read_csv_rows(included_studies_path)
    return {
        "n_rows": len(rows),
        "fields": fields,
        "public_identifier_coverage": _public_study_identifier_coverage(rows),
        "local_identifier_coverage": _coverage(rows, LOCAL_STUDY_ID_FIELDS),
        "source_provenance_coverage": _coverage(rows, SOURCE_PROVENANCE_FIELDS),
        "sample_size_coverage": _coverage(rows, SAMPLE_SIZE_FIELDS),
        "has_public_identifier_fields": any(
            field in fields
            for field in (*PUBLIC_STUDY_ID_FIELDS, *PMID_LIKE_STUDY_ID_FIELDS)
        ),
        "has_source_provenance_fields": any(
            field in fields for field in SOURCE_PROVENANCE_FIELDS
        ),
    }


def _provenance_completeness(path: Path | None) -> dict[str, Any]:
    data = _load_json_dict(path)
    present = [
        field_group
        for field_group in PROVENANCE_REQUIRED_FIELDS
        if _has_any_key(data, field_group)
    ]
    br_call_count = 0
    for key in (
        "br_calls",
        "br_calls_made",
        "br_tool_calls",
        "brain_researcher_calls",
    ):
        value = data.get(key)
        if isinstance(value, list):
            br_call_count += len(value)
        elif value not in (None, "", {}, []):
            br_call_count += 1
    return {
        "score": len(present) / len(PROVENANCE_REQUIRED_FIELDS)
        if PROVENANCE_REQUIRED_FIELDS
        else None,
        "present_fields": [field_group[0] for field_group in present],
        "required_fields": [field_group[0] for field_group in PROVENANCE_REQUIRED_FIELDS],
        "br_call_count": br_call_count,
    }


def _claim_consistency_proxy(
    *,
    report_path: Path | None,
    n_coordinate_rows: int | None,
    n_included_studies: int | None,
    map_generated: bool,
) -> dict[str, Any]:
    if report_path is None or not report_path.exists():
        return {"score": 0.0, "reason": "missing_spatial_report"}
    text = report_path.read_text(encoding="utf-8", errors="ignore").lower()
    checks = {
        "mentions_ale": "ale" in text,
        "mentions_coordinate_count": (
            n_coordinate_rows is not None and str(n_coordinate_rows) in text
        ),
        "mentions_study_count": (
            n_included_studies is not None and str(n_included_studies) in text
        ),
        "mentions_map_output": (not map_generated) or any(
            token in text for token in ("map", ".nii", "nifti")
        ),
    }
    return {
        "score": sum(1 for value in checks.values() if value) / len(checks),
        "checks": checks,
    }


def _failure_diagnosis_quality(
    *,
    status: str,
    status_reasons: list[str],
    data: dict[str, Any],
    provenance_data: dict[str, Any],
) -> dict[str, Any]:
    if status == "evaluable":
        return {"score": None, "status": "not_applicable"}
    explicit_reasons = bool(status_reasons)
    failure_fields = any(
        value not in (None, "", [], {})
        for value in (
            data.get("error"),
            data.get("failure_reason"),
            data.get("failure_reasons"),
            provenance_data.get("failure_reason"),
            provenance_data.get("failure_reasons"),
        )
    )
    return {
        "score": 1.0 if explicit_reasons or failure_fields else 0.0,
        "status": "scored",
        "has_status_reasons": explicit_reasons,
        "has_failure_fields": failure_fields,
    }


def _is_nifti(path: Path) -> bool:
    name = path.name
    return name.endswith(".nii") or name.endswith(".nii.gz")


def _declared_map_paths(data: dict[str, Any]) -> dict[str, Any]:
    map_paths = _nested_get(data, ("ale", "map_paths"))
    if isinstance(map_paths, dict):
        return map_paths
    map_paths = data.get("map_paths")
    if isinstance(map_paths, dict):
        return map_paths
    return {}


def _present_map_paths(case: DiscoveredCase) -> list[Path]:
    present: list[Path] = []
    for value in _declared_map_paths(case.data).values():
        resolved = _resolve_existing_path(
            value,
            case_dir=case.case_dir,
            condition_path=case.condition_path,
        )
        if resolved and _is_nifti(resolved):
            present.append(resolved)

    for maps_dir in [case.case_dir / "ale_maps"]:
        if maps_dir.exists():
            present.extend(path for path in sorted(maps_dir.rglob("*")) if _is_nifti(path))

    declared_maps_dir = _nested_get(case.data, ("outputs", "ale_maps_dir"))
    resolved_maps_dir = _resolve_existing_path(
        declared_maps_dir,
        case_dir=case.case_dir,
        condition_path=case.condition_path,
    )
    if resolved_maps_dir and resolved_maps_dir.is_dir():
        present.extend(path for path in sorted(resolved_maps_dir.rglob("*")) if _is_nifti(path))

    unique: dict[str, Path] = {}
    for path in present:
        unique[str(path)] = path
    return sorted(unique.values())


def _extract_spatial_metrics(data: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    split_half_metrics = _nested_get(data, ("split_half", "z_map_metrics"))
    if isinstance(split_half_metrics, dict):
        metrics["split_half_z_map"] = split_half_metrics

    reference_metrics = _nested_get(data, ("reference_comparison", "z_map_metrics"))
    if isinstance(reference_metrics, dict):
        metrics["reference_z_map"] = reference_metrics

    for key in ("spatial_metrics", "z_map_metrics"):
        value = data.get(key)
        if isinstance(value, dict):
            metrics[key] = value
    return metrics


def _explicit_failure_reason(data: dict[str, Any]) -> str | None:
    status = str(data.get("status") or data.get("run_status") or "").lower()
    if status in STATUS_VALUES_FAILED:
        return f"reported status={status}"
    if data.get("success") is False or data.get("ok") is False:
        return "reported success=false"
    if data.get("error"):
        return f"reported error={data.get('error')}"
    return None


def _field_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _as_int(data.get(key))
        if value is not None:
            return value
    return None


def _classify_case(
    *,
    explicit_failure: str | None,
    map_generated: bool,
    degraded_fallback_map: bool,
    n_coordinate_rows: int | None,
    n_included_studies: int | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if explicit_failure:
        return "failed", [explicit_failure]
    if not map_generated:
        reasons.append("missing ALE map artifact")
    if degraded_fallback_map:
        reasons.append("degraded fallback ALE map evidence")
    if not n_coordinate_rows:
        reasons.append("missing or zero coordinate rows")
    if not n_included_studies:
        reasons.append("missing or zero included studies")

    if not reasons:
        return "evaluable", []
    if not map_generated and not n_coordinate_rows and not n_included_studies:
        return "failed", reasons
    return "degraded", reasons


def _normalize_artifacts(case_dir: Path) -> dict[str, Any]:
    from scripts.neurometabench_v1.layer_b_artifact_normalizer import (
        normalize_case_bundle,
    )

    try:
        return normalize_case_bundle(case_dir)
    except Exception as exc:  # pragma: no cover - defensive post-hoc guard
        return {
            "case_dir": str(case_dir),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _trace_br_anchors(case_dir: Path) -> dict[str, Any]:
    from scripts.neurometabench_v1.layer_b_br_anchor_tracer import (
        trace_case_br_anchors,
    )

    try:
        return trace_case_br_anchors(case_dir)
    except Exception as exc:  # pragma: no cover - defensive post-hoc guard
        return {
            "case_dir": str(case_dir),
            "summary": {
                "br_call_count": 0,
                "br_anchor_count": 0,
                "retrieved_or_audited_anchor_present": False,
                "artifact_or_report_consumes_br_result": False,
                "br_effective_use_pass": False,
                "br_reconciliation_anchor_present": False,
                "br_reconciliation_anchor_count": 0,
                "br_reconciliation_anchor_valid_count": 0,
                "br_reconciliation_anchor_consumed_count": 0,
                "br_reconciliation_anchor_changed_count": 0,
                "br_reconciliation_anchor_changed_consumed_count": 0,
                "br_reconciliation_anchor_pass": False,
            },
            "br_reconciliation_anchors": {
                "present": False,
                "n_anchors": 0,
                "n_valid_anchors": 0,
                "n_consumed": 0,
                "pass": False,
                "invalid_reasons": [f"{type(exc).__name__}: {exc}"],
            },
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_case(
    case: DiscoveredCase,
    *,
    normalize_artifacts: bool = False,
    trace_br_anchors: bool = False,
) -> dict[str, Any]:
    data = case.data
    case_id, meta_pmid = _case_identity(data, case.source_file)

    coordinate_table = _artifact_presence(
        label="coordinate_table",
        declared_path=_nested_get(data, ("outputs", "coordinate_table")),
        fallback_paths=[case.case_dir / "coordinate_table.csv"],
        case_dir=case.case_dir,
        condition_path=case.condition_path,
    )
    included_studies = _artifact_presence(
        label="included_studies",
        declared_path=_nested_get(data, ("outputs", "included_studies")),
        fallback_paths=[case.case_dir / "included_studies.csv"],
        case_dir=case.case_dir,
        condition_path=case.condition_path,
    )
    provenance_manifest = _artifact_presence(
        label="provenance_manifest",
        declared_path=_nested_get(data, ("outputs", "provenance_manifest")),
        fallback_paths=[case.case_dir / "provenance_manifest.json"],
        case_dir=case.case_dir,
        condition_path=case.condition_path,
    )
    metrics_json = _artifact_presence(
        label="metrics_json",
        declared_path=_nested_get(data, ("outputs", "metrics")),
        fallback_paths=[case.case_dir / "metrics.json"],
        case_dir=case.case_dir,
        condition_path=case.condition_path,
    )
    summary_json = {
        "present": case.source_file.name != "metrics.json",
        "path": str(case.source_file) if case.source_file.name != "metrics.json" else None,
        "declared_path": None,
        "label": "summary_json",
    }

    map_paths = _present_map_paths(case)
    map_generated = bool(map_paths)
    n_coordinate_rows = _field_int(
        data,
        ("n_coordinate_rows", "n_coordinates", "n_dataset_coordinates"),
    )
    if n_coordinate_rows is None:
        n_coordinate_rows = _as_int(_nested_get(data, ("ale", "n_dataset_coordinates")))
    if n_coordinate_rows is None:
        n_coordinate_rows = _count_csv_rows(
            Path(coordinate_table["path"]) if coordinate_table["path"] else None
        )

    n_included_studies = _field_int(
        data,
        ("n_included_studies", "n_nimads_studies", "n_studies"),
    )
    if n_included_studies is None and isinstance(data.get("included_studies"), list):
        n_included_studies = len(data["included_studies"])
    if n_included_studies is None:
        n_included_studies = _count_csv_rows(
            Path(included_studies["path"]) if included_studies["path"] else None
        )

    split_half_status = _nested_get(data, ("split_half", "status")) or data.get(
        "split_half_status"
    )
    explicit_failure = _explicit_failure_reason(data)
    fallback_map_check = _fallback_map_evidence(case)
    degraded_fallback_map = fallback_map_check["detected"]
    status, status_reasons = _classify_case(
        explicit_failure=explicit_failure,
        map_generated=map_generated,
        degraded_fallback_map=degraded_fallback_map,
        n_coordinate_rows=n_coordinate_rows,
        n_included_studies=n_included_studies,
    )

    required_artifacts = {
        "metrics_json": metrics_json,
        "summary_json": summary_json,
        "coordinate_table": coordinate_table,
        "included_studies": included_studies,
        "provenance_manifest": provenance_manifest,
        "ale_map": {
            "present": map_generated,
            "degraded_fallback_map": degraded_fallback_map,
            "paths": [str(path) for path in map_paths],
            "declared_paths": _declared_map_paths(data),
            "label": "ale_map",
        },
    }
    map_checksums = {path.name: _sha256_file(path) for path in map_paths}
    artifact_checksums = {
        "coordinate_table": _sha256_file(
            Path(coordinate_table["path"]) if coordinate_table["path"] else None
        ),
        "included_studies": _sha256_file(
            Path(included_studies["path"]) if included_studies["path"] else None
        ),
        "ale_maps": map_checksums,
    }
    required_artifacts["ale_map"]["checksums"] = map_checksums
    provenance = {
        "manifest_present": provenance_manifest["present"],
        "manifest_path": provenance_manifest["path"],
    }
    provenance_path = Path(provenance_manifest["path"]) if provenance_manifest["path"] else None
    report_path = case.case_dir / "spatial_report.md"
    included_studies_path = (
        Path(included_studies["path"]) if included_studies["path"] else None
    )
    provenance_data = _load_json_dict(provenance_path)
    normalization_manifest = (
        _normalize_artifacts(case.case_dir) if normalize_artifacts else None
    )
    br_anchor_trace = _trace_br_anchors(case.case_dir) if trace_br_anchors else None
    br_relevant_metrics = {
        "study_reconciliation": _study_reconciliation_metrics(included_studies_path),
        "provenance_completeness": _provenance_completeness(provenance_path),
        "claim_consistency": _claim_consistency_proxy(
            report_path=report_path,
            n_coordinate_rows=n_coordinate_rows,
            n_included_studies=n_included_studies,
            map_generated=map_generated,
        ),
        "failure_diagnosis_quality": _failure_diagnosis_quality(
            status=status,
            status_reasons=status_reasons,
            data=data,
            provenance_data=provenance_data,
        ),
    }
    if br_anchor_trace is not None:
        br_relevant_metrics["br_anchor_trace"] = br_anchor_trace.get("summary", {})
        br_relevant_metrics["br_reconciliation_anchors"] = br_anchor_trace.get(
            "br_reconciliation_anchors", {}
        )
    normalization_metrics = None
    if normalization_manifest is not None:
        normalized_contract = normalization_manifest.get("normalized_contract", {})
        normalization_metrics = {
            "coordinate_table": normalized_contract.get("coordinate_table", {}),
            "included_studies": normalized_contract.get("included_studies", {}),
            "normalization_delta": normalization_manifest.get(
                "normalization_delta", {}
            ),
            "error": normalization_manifest.get("error"),
        }
    deterministic_artifact_metrics = {
        "status": status,
        "map_generated": map_generated,
        "degraded_fallback_map": degraded_fallback_map,
        "fallback_map_check": fallback_map_check,
        "n_coordinate_rows": n_coordinate_rows,
        "n_included_studies": n_included_studies,
        "n_map_files": len(map_paths),
        "study_set_f1": {
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": "not_computed_without_case_gold_context",
        },
        "coordinate_extraction_agreement": {
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": "missing_pure_nimare_control",
        },
        "coordinate_canonical_f1": {
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": "missing_pure_nimare_control",
        },
        "local_study_set_f1": {
            "precision": None,
            "recall": None,
            "f1": None,
            "reason": "missing_pure_nimare_control",
        },
        "ale_map_spatial_correlation": _metric_value(
            None, "missing_pure_nimare_control"
        ),
        "dice_top5": _metric_value(None, "missing_pure_nimare_control"),
        "exact_match_to_pure_nimare": {
            "all_maps": None,
            "coordinate_table": None,
            "included_studies": None,
            "reason": "missing_pure_nimare_control",
        },
    }
    metric_contract = {
        "study_set_f1": deterministic_artifact_metrics["study_set_f1"],
        "coordinate_extraction_agreement": deterministic_artifact_metrics[
            "coordinate_extraction_agreement"
        ],
        "coordinate_canonical_f1": deterministic_artifact_metrics[
            "coordinate_canonical_f1"
        ],
        "local_study_set_f1": deterministic_artifact_metrics["local_study_set_f1"],
        "map_generated": _metric_value(map_generated),
        "degraded_fallback_map": _metric_value(
            degraded_fallback_map,
            fallback_map_check.get("reason"),
        ),
        "coordinate_rows": _metric_value(n_coordinate_rows),
        "study_rows": _metric_value(n_included_studies),
        "exact_match_to_pure_nimare": deterministic_artifact_metrics[
            "exact_match_to_pure_nimare"
        ],
        "ale_map_spatial_correlation": deterministic_artifact_metrics[
            "ale_map_spatial_correlation"
        ],
        "dice_top5": deterministic_artifact_metrics["dice_top5"],
        "pmid_study_reconciliation": br_relevant_metrics["study_reconciliation"],
        "br_reconciliation_anchors": br_relevant_metrics.get(
            "br_reconciliation_anchors", {}
        ),
        "provenance_completeness": br_relevant_metrics["provenance_completeness"],
        "claim_consistency": br_relevant_metrics["claim_consistency"],
        "failure_diagnosis_quality": br_relevant_metrics[
            "failure_diagnosis_quality"
        ],
    }

    return {
        "condition": case.condition,
        "case_key": _case_key(data, case.source_file, case.case_dir),
        "case_id": case_id,
        "meta_pmid": meta_pmid,
        "topic": data.get("topic"),
        "project_key": data.get("project_key"),
        "case_dir": str(case.case_dir),
        "source_file": str(case.source_file),
        "source_kind": case.source_kind,
        "status": status,
        "status_reasons": status_reasons,
        "map_generated": map_generated,
        "degraded_fallback_map": degraded_fallback_map,
        "fallback_map_check": fallback_map_check,
        "n_coordinate_rows": n_coordinate_rows,
        "n_included_studies": n_included_studies,
        "split_half_status": split_half_status,
        "spatial_metrics": _extract_spatial_metrics(data),
        "provenance": provenance,
        "required_artifacts": required_artifacts,
        "artifact_checksums": artifact_checksums,
        "metric_layers": {
            "deterministic_artifact": deterministic_artifact_metrics,
            "br_relevant_audit": br_relevant_metrics,
            "metric_contract": metric_contract,
            "normalization": normalization_metrics,
        },
    }


def _status_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(case["status"] for case in cases)
    return {status: counts.get(status, 0) for status in ("evaluable", "degraded", "failed")}


def _condition_status(cases: list[dict[str, Any]]) -> str:
    if not cases:
        return "failed"
    counts = _status_counts(cases)
    if counts["failed"]:
        return "failed"
    if counts["degraded"]:
        return "degraded"
    return "evaluable"


def summarize_condition(
    condition: ConditionInput,
    *,
    normalize_artifacts: bool = False,
    trace_br_anchors: bool = False,
) -> dict[str, Any]:
    discovered = discover_cases(condition)
    cases = [
        summarize_case(
            case,
            normalize_artifacts=normalize_artifacts,
            trace_br_anchors=trace_br_anchors,
        )
        for case in discovered
    ]
    return {
        "name": condition.name,
        "path": str(condition.path),
        "status": _condition_status(cases),
        "status_counts": _status_counts(cases),
        "n_cases": len(cases),
        "n_cases_with_maps": sum(1 for case in cases if case["map_generated"]),
        "total_coordinate_rows": sum(case.get("n_coordinate_rows") or 0 for case in cases),
        "total_included_studies": sum(case.get("n_included_studies") or 0 for case in cases),
        "errors": [] if cases else ["no Layer B case outputs discovered"],
        "cases": cases,
    }


def _case_index(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for condition in conditions:
        for case in condition["cases"]:
            entry = by_key.setdefault(
                case["case_key"],
                {
                    "case_key": case["case_key"],
                    "case_id": case.get("case_id"),
                    "meta_pmid": case.get("meta_pmid"),
                    "topic": case.get("topic"),
                    "conditions": {},
                },
            )
            entry["conditions"][condition["name"]] = {
                "status": case["status"],
                "map_generated": case["map_generated"],
                "degraded_fallback_map": case.get("degraded_fallback_map"),
                "n_coordinate_rows": case.get("n_coordinate_rows"),
                "n_included_studies": case.get("n_included_studies"),
                "split_half_status": case.get("split_half_status"),
                "metric_layers": case.get("metric_layers"),
                "control_coordinate_table_exact_match": _nested_get(
                    case,
                    ("control_comparison", "coordinate_table_exact_match"),
                ),
                "control_all_maps_exact_match": _nested_get(
                    case,
                    ("control_comparison", "all_maps_exact_match"),
                ),
            }
    return [by_key[key] for key in sorted(by_key)]


def _control_key(case: dict[str, Any]) -> str:
    return str(case.get("meta_pmid") or case.get("case_id") or case["case_key"])


def _artifact_path(case: dict[str, Any], artifact_name: str) -> Path | None:
    artifact = (case.get("required_artifacts") or {}).get(artifact_name) or {}
    path = artifact.get("path")
    return Path(path) if path else None


def _map_paths(case: dict[str, Any]) -> list[str]:
    artifact = (case.get("required_artifacts") or {}).get("ale_map") or {}
    paths = artifact.get("paths")
    return list(paths) if isinstance(paths, list) else []


def _compare_case_to_control(
    *,
    case: dict[str, Any],
    control_case: dict[str, Any],
) -> dict[str, Any]:
    case_checksums = case.get("artifact_checksums") or {}
    control_checksums = control_case.get("artifact_checksums") or {}
    case_maps = case_checksums.get("ale_maps") or {}
    control_maps = control_checksums.get("ale_maps") or {}
    map_exact_matches = {
        name: case_maps.get(name) == checksum
        for name, checksum in sorted(control_maps.items())
        if checksum is not None
    }
    case_coordinate_table = _artifact_path(case, "coordinate_table")
    control_coordinate_table = _artifact_path(control_case, "coordinate_table")
    spatial_agreement = _spatial_map_agreement(
        case_paths=_map_paths(case),
        control_paths=_map_paths(control_case),
    )
    coordinate_extraction_agreement = _coordinate_agreement(
        case_path=case_coordinate_table,
        control_path=control_coordinate_table,
        include_identifiers=False,
    )
    coordinate_canonical_agreement = _coordinate_agreement(
        case_path=case_coordinate_table,
        control_path=control_coordinate_table,
        include_identifiers=True,
    )
    coordinate_extraction_agreement = _spatial_equivalent_coordinate_agreement(
        coordinate_extraction_agreement,
        spatial_agreement=spatial_agreement,
    )
    coordinate_canonical_agreement = _spatial_equivalent_coordinate_agreement(
        coordinate_canonical_agreement,
        spatial_agreement=spatial_agreement,
    )
    local_study_agreement = _local_study_set_agreement(
        case_path=_artifact_path(case, "included_studies"),
        control_path=_artifact_path(control_case, "included_studies"),
    )
    return {
        "control_condition": control_case.get("condition"),
        "control_case_key": control_case.get("case_key"),
        "coordinate_rows_delta": (case.get("n_coordinate_rows") or 0)
        - (control_case.get("n_coordinate_rows") or 0),
        "included_studies_delta": (case.get("n_included_studies") or 0)
        - (control_case.get("n_included_studies") or 0),
        "coordinate_table_exact_match": (
            case_checksums.get("coordinate_table")
            == control_checksums.get("coordinate_table")
        ),
        "included_studies_exact_match": (
            case_checksums.get("included_studies")
            == control_checksums.get("included_studies")
        ),
        "map_exact_matches": map_exact_matches,
        "all_maps_exact_match": bool(map_exact_matches)
        and all(map_exact_matches.values())
        and set(case_maps) == set(control_maps),
        "coordinate_extraction_agreement": coordinate_extraction_agreement,
        "coordinate_canonical_f1": coordinate_canonical_agreement,
        "local_study_set_f1": local_study_agreement,
        "spatial_map_agreement": spatial_agreement,
    }


def _add_control_comparisons(conditions: list[dict[str, Any]]) -> None:
    control_condition = next(
        (condition for condition in conditions if condition["name"] == "pure_nimare"),
        None,
    )
    if control_condition is None:
        return
    controls = {_control_key(case): case for case in control_condition["cases"]}
    for condition in conditions:
        if condition is control_condition:
            continue
        for case in condition["cases"]:
            control_case = controls.get(_control_key(case))
            if control_case is None:
                continue
            case["control_comparison"] = _compare_case_to_control(
                case=case,
                control_case=control_case,
            )
            case["metric_layers"]["deterministic_artifact"]["control_comparison"] = case[
                "control_comparison"
            ]
            deterministic = case["metric_layers"]["deterministic_artifact"]
            contract = case["metric_layers"]["metric_contract"]
            control = case["control_comparison"]
            deterministic["coordinate_extraction_agreement"] = control[
                "coordinate_extraction_agreement"
            ]
            deterministic["coordinate_canonical_f1"] = control[
                "coordinate_canonical_f1"
            ]
            deterministic["local_study_set_f1"] = control["local_study_set_f1"]
            deterministic["ale_map_spatial_correlation"] = _metric_value(
                control["spatial_map_agreement"].get("spatial_correlation"),
                control["spatial_map_agreement"].get("reason"),
            )
            deterministic["dice_top5"] = _metric_value(
                control["spatial_map_agreement"].get("dice_top5"),
                control["spatial_map_agreement"].get("reason"),
            )
            deterministic["exact_match_to_pure_nimare"] = {
                "all_maps": control["all_maps_exact_match"],
                "coordinate_table": control["coordinate_table_exact_match"],
                "included_studies": control["included_studies_exact_match"],
                "reason": None,
            }
            contract["coordinate_extraction_agreement"] = deterministic[
                "coordinate_extraction_agreement"
            ]
            contract["coordinate_canonical_f1"] = deterministic[
                "coordinate_canonical_f1"
            ]
            contract["local_study_set_f1"] = deterministic["local_study_set_f1"]
            contract["ale_map_spatial_correlation"] = deterministic[
                "ale_map_spatial_correlation"
            ]
            contract["dice_top5"] = deterministic["dice_top5"]
            contract["exact_match_to_pure_nimare"] = deterministic[
                "exact_match_to_pure_nimare"
            ]


def _add_study_set_metrics(
    conditions: list[dict[str, Any]],
    *,
    cases_path: Path,
) -> None:
    gold_by_meta_pmid = _load_case_gold_pmids(cases_path)
    for condition in conditions:
        for case in condition["cases"]:
            meta_pmid = str(case.get("meta_pmid") or "").strip()
            gold = gold_by_meta_pmid.get(meta_pmid, set())
            included_path = _artifact_path(case, "included_studies")
            predicted = _extract_public_study_ids(included_path)
            metrics = _precision_recall_f1(predicted=predicted, gold=gold)
            case["metric_layers"]["deterministic_artifact"]["study_set_f1"] = metrics
            case["metric_layers"]["metric_contract"]["study_set_f1"] = metrics


def _summarize_metric_layers(condition: dict[str, Any]) -> dict[str, Any]:
    cases = condition["cases"]
    deterministic = [
        case.get("metric_layers", {}).get("deterministic_artifact", {}) for case in cases
    ]
    br_relevant = [
        case.get("metric_layers", {}).get("br_relevant_audit", {}) for case in cases
    ]
    study_reconciliation = [
        metrics.get("study_reconciliation", {}) for metrics in br_relevant
    ]
    provenance = [
        metrics.get("provenance_completeness", {}) for metrics in br_relevant
    ]
    claim = [metrics.get("claim_consistency", {}) for metrics in br_relevant]
    failure = [
        metrics.get("failure_diagnosis_quality", {}) for metrics in br_relevant
    ]
    br_anchor_trace = [metrics.get("br_anchor_trace", {}) for metrics in br_relevant]
    normalization = [
        case.get("metric_layers", {}).get("normalization", {}) or {} for case in cases
    ]
    normalized_coordinates = [
        metrics.get("coordinate_table", {}) for metrics in normalization
    ]
    normalized_studies = [
        metrics.get("included_studies", {}) for metrics in normalization
    ]
    normalization_delta = [
        metrics.get("normalization_delta", {}) for metrics in normalization
    ]
    control = [
        metrics.get("control_comparison", {}) for metrics in deterministic
    ]
    total_br_calls = sum(
        (
            trace.get("br_call_count")
            if trace.get("br_call_count") is not None
            else provenance_metrics.get("br_call_count") or 0
        )
        for trace, provenance_metrics in zip(br_anchor_trace, provenance)
    )
    return {
        "deterministic_artifact": {
            "map_generation_rate": _rate(
                [metrics.get("map_generated") for metrics in deterministic]
            ),
            "degraded_fallback_map_rate": _rate(
                [metrics.get("degraded_fallback_map") for metrics in deterministic]
            ),
            "mean_coordinate_rows": _mean(
                [metrics.get("n_coordinate_rows") for metrics in deterministic]
            ),
            "mean_included_studies": _mean(
                [metrics.get("n_included_studies") for metrics in deterministic]
            ),
            "control_map_exact_match_rate": _rate(
                [metrics.get("all_maps_exact_match") for metrics in control]
            ),
            "control_coordinate_table_exact_match_rate": _rate(
                [metrics.get("coordinate_table_exact_match") for metrics in control]
            ),
            "mean_study_set_f1": _mean(
                [
                    metrics.get("study_set_f1", {}).get("f1")
                    for metrics in deterministic
                ]
            ),
            "mean_coordinate_extraction_agreement": _mean(
                [
                    metrics.get("coordinate_extraction_agreement", {}).get("f1")
                    for metrics in deterministic
                ]
            ),
            "mean_coordinate_canonical_f1": _mean(
                [
                    metrics.get("coordinate_canonical_f1", {}).get("f1")
                    for metrics in deterministic
                ]
            ),
            "mean_local_study_set_f1": _mean(
                [
                    metrics.get("local_study_set_f1", {}).get("f1")
                    for metrics in deterministic
                ]
            ),
            "mean_ale_map_spatial_correlation": _metric_mean(
                [metrics.get("ale_map_spatial_correlation") for metrics in deterministic]
            ),
            "mean_dice_top5": _metric_mean(
                [metrics.get("dice_top5") for metrics in deterministic]
            ),
        },
        "br_relevant_audit": {
            "mean_public_identifier_coverage": _mean(
                [
                    metrics.get("public_identifier_coverage")
                    for metrics in study_reconciliation
                ]
            ),
            "mean_local_identifier_coverage": _mean(
                [
                    metrics.get("local_identifier_coverage")
                    for metrics in study_reconciliation
                ]
            ),
            "mean_source_provenance_coverage": _mean(
                [
                    metrics.get("source_provenance_coverage")
                    for metrics in study_reconciliation
                ]
            ),
            "mean_sample_size_coverage": _mean(
                [metrics.get("sample_size_coverage") for metrics in study_reconciliation]
            ),
            "mean_provenance_completeness": _mean(
                [metrics.get("score") for metrics in provenance]
            ),
            "mean_claim_consistency_proxy": _mean(
                [metrics.get("score") for metrics in claim]
            ),
            "mean_failure_diagnosis_quality": _mean(
                [metrics.get("score") for metrics in failure]
            ),
            "total_br_calls": total_br_calls,
            "br_effective_use_rate": _rate(
                [metrics.get("br_effective_use_pass") for metrics in br_anchor_trace]
            ),
        },
        "normalization": {
            "mean_coordinate_parseability": _mean(
                [
                    metrics.get("coordinate_parseability")
                    for metrics in normalized_coordinates
                ]
            ),
            "mean_normalized_public_identifier_coverage": _mean(
                [
                    metrics.get("public_identifier_coverage")
                    for metrics in normalized_studies
                ]
            ),
            "mean_normalized_source_provenance_coverage": _mean(
                [
                    metrics.get("source_provenance_coverage")
                    for metrics in normalized_studies
                ]
            ),
            "total_normalization_repairs": sum(
                metrics.get("n_repairs") or 0 for metrics in normalization_delta
            ),
        },
    }


def _add_metric_layer_summaries(conditions: list[dict[str, Any]]) -> None:
    for condition in conditions:
        condition["metric_layers"] = _summarize_metric_layers(condition)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _md_escape(value: Any) -> str:
    return _format_value(value).replace("|", "\\|").replace("\n", " ")


def _primary_spatial_metric(case: dict[str, Any], key: str) -> Any:
    for group in case.get("spatial_metrics", {}).values():
        if isinstance(group, dict) and key in group:
            return group[key]
    return None


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Layer B Comparison Summary",
        "",
        "| Condition | Status | Cases | Evaluable | Degraded | Failed | Maps | Coord rows | Studies |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in payload["conditions"]:
        counts = condition["status_counts"]
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_escape(condition["name"]),
                    _md_escape(condition["status"]),
                    _md_escape(condition["n_cases"]),
                    _md_escape(counts["evaluable"]),
                    _md_escape(counts["degraded"]),
                    _md_escape(counts["failed"]),
                    _md_escape(condition["n_cases_with_maps"]),
                    _md_escape(condition["total_coordinate_rows"]),
                    _md_escape(condition["total_included_studies"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Metric Layers",
            "",
            "| Condition | Map gen | Study F1 | Local study F1 | Coord F1 | Canon coord F1 | Spatial r | Dice top5 | Control maps | Control coord | Public ID | Local ID | Source prov | Sample size | Prov complete | Claim | Failure diag | BR calls |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for condition in payload["conditions"]:
        deterministic = condition.get("metric_layers", {}).get(
            "deterministic_artifact", {}
        )
        br_relevant = condition.get("metric_layers", {}).get("br_relevant_audit", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_escape(condition["name"]),
                    _md_escape(deterministic.get("map_generation_rate")),
                    _md_escape(deterministic.get("mean_study_set_f1")),
                    _md_escape(deterministic.get("mean_local_study_set_f1")),
                    _md_escape(
                        deterministic.get("mean_coordinate_extraction_agreement")
                    ),
                    _md_escape(deterministic.get("mean_coordinate_canonical_f1")),
                    _md_escape(
                        deterministic.get("mean_ale_map_spatial_correlation")
                    ),
                    _md_escape(deterministic.get("mean_dice_top5")),
                    _md_escape(deterministic.get("control_map_exact_match_rate")),
                    _md_escape(
                        deterministic.get("control_coordinate_table_exact_match_rate")
                    ),
                    _md_escape(br_relevant.get("mean_public_identifier_coverage")),
                    _md_escape(br_relevant.get("mean_local_identifier_coverage")),
                    _md_escape(br_relevant.get("mean_source_provenance_coverage")),
                    _md_escape(br_relevant.get("mean_sample_size_coverage")),
                    _md_escape(br_relevant.get("mean_provenance_completeness")),
                    _md_escape(br_relevant.get("mean_claim_consistency_proxy")),
                    _md_escape(br_relevant.get("mean_failure_diagnosis_quality")),
                    _md_escape(br_relevant.get("total_br_calls")),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Condition | Case | Status | Map | Coord rows | Studies | Split half | Pearson | Dice | Control maps | Control coord | Provenance |",
            "| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for condition in payload["conditions"]:
        for case in condition["cases"]:
            case_label = case.get("case_id") or case.get("meta_pmid") or case["case_key"]
            control_comparison = case.get("control_comparison") or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_escape(condition["name"]),
                        _md_escape(case_label),
                        _md_escape(case["status"]),
                        "yes" if case["map_generated"] else "no",
                        _md_escape(case.get("n_coordinate_rows")),
                        _md_escape(case.get("n_included_studies")),
                        _md_escape(case.get("split_half_status")),
                        _md_escape(_primary_spatial_metric(case, "pearson_union_positive")),
                        _md_escape(_primary_spatial_metric(case, "dice_top5_positive")),
                        _md_escape(control_comparison.get("all_maps_exact_match")),
                        _md_escape(
                            control_comparison.get("coordinate_table_exact_match")
                        ),
                        "yes" if case["provenance"]["manifest_present"] else "no",
                    ]
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def layer_b_contract() -> dict[str, Any]:
    return {
        "required_case_artifacts": [
            "metrics.json",
            "coordinate_table.csv",
            "included_studies.csv",
            "provenance_manifest.json",
            "spatial_report.md",
        ],
        "optional_map_artifacts": [
            "ale_maps/<meta_pmid>_stat.nii.gz",
            "ale_maps/<meta_pmid>_z.nii.gz",
            "ale_maps/<meta_pmid>_p.nii.gz",
        ],
        "br_required_case_artifacts": [
            "br_reconciliation_anchors.json",
        ],
        "br_reconciliation_anchor_contract": {
            "top_level": "`anchors` list",
            "recommended_anchor_shape": {
                "target_artifact": "spatial_report.md",
                "target_field": "study_pmid",
                "canonical_value": "12345678",
                "evidence_source": "BR MCP / file search / KG lookup",
                "evidence_summary": "Audited local study to PMID 12345678.",
                "confidence": "high",
                "changed_bundle": False,
            },
            "target_fields": [
                "study_id",
                "study_pmid",
                "doi",
                "pmcid",
                "source_asset",
                "source_file",
                "sample_size",
                "coordinate_space",
                "original_study_ids",
            ],
            "target_artifacts": [
                "spatial_report.md",
                "provenance_manifest.json",
                "br_reconciliation_anchors.json",
                "included_studies.csv",
                "coordinate_table.csv",
                "metrics.json",
                "pmid_study_reconciliation.json",
                "normalization_manifest.json",
            ],
            "safe_reproduction_table_write_policy": (
                "conservative: BR is enrichment-first and correction-second; "
                "coordinate_table.csv and included_studies.csv are reproduction "
                "artifacts owned by local NiMADS/NiMARE extraction"
            ),
            "pass_rule": (
                "at least one valid anchor, all anchors target canonical fields, "
                "at least one anchor is consumed by an artifact or report, and "
                "every changed_bundle=true anchor is consumed"
            ),
            "canonical_value_rule": (
                "canonical_value should be the exact short value copied into an "
                "artifact or spatial_report.md; explanatory prose belongs in "
                "evidence_summary"
            ),
            "changed_bundle_rule": (
                "set changed_bundle=true only when the exact canonical_value appears "
                "in the named target artifact or spatial_report.md; use false for "
                "audit-only provenance confirmation"
            ),
            "report_consumption_hint": (
                "A compact 'BR reconciliation anchors' line/table in spatial_report.md "
                "may repeat changed canonical values exactly for auditable consumption"
            ),
            "science_table_guardrail": (
                "do not split, merge, rename, case-normalize, punctuation-normalize, "
                "alias-expand, transform coordinates, change coordinate spaces, "
                "filter annotation subsets, or alter analysis IDs based on BR "
                "evidence; prefer spatial_report.md, provenance_manifest.json, or "
                "br_reconciliation_anchors.json for audit anchors unless BR directly "
                "corrects or fills a blank or unparseable table field"
            ),
        },
        "metric_contract_keys": [
            "study_set_f1",
            "local_study_set_f1",
            "coordinate_extraction_agreement",
            "coordinate_canonical_f1",
            "map_generated",
            "degraded_fallback_map",
            "coordinate_rows",
            "study_rows",
            "exact_match_to_pure_nimare",
            "ale_map_spatial_correlation",
            "dice_top5",
            "pmid_study_reconciliation",
            "br_reconciliation_anchors",
            "provenance_completeness",
            "claim_consistency",
            "failure_diagnosis_quality",
        ],
        "strict_v2_recommended_requirements": {
            "map_generation_pass": True,
            "scientific_similarity_pass": True,
            "provenance_pass": True,
            "claim_consistency_pass": True,
            "local_study_set_f1_min": 0.98,
            "coordinate_canonical_f1_min": 0.98,
        },
        "diagnostic_report_keys": [
            "operational_completion",
            "harness_clean_pass",
            "correct_strict",
            "normalized_science_score",
            "degraded_fallback_map",
            "local_study_set_f1",
            "coordinate_canonical_f1",
            "spatial_correlation",
            "dice_top5",
            "br_effective_use_pass",
            "br_reconciliation_anchor_pass",
            "br_reconciliation_anchor_score",
            "provenance_complete_score",
            "claim_consistency_score",
            "br_reconciliation_score",
            "br_reconciliation_gain",
            "identifier_coverage_delta",
            "provenance_enrichment_delta",
            "normalized_vs_raw_recovery",
        ],
    }


def build_summary(
    conditions: list[ConditionInput],
    output_dir: Path,
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    normalize_artifacts: bool = False,
    trace_br_anchors: bool = False,
) -> dict[str, Any]:
    condition_summaries = [
        summarize_condition(
            condition,
            normalize_artifacts=normalize_artifacts,
            trace_br_anchors=trace_br_anchors,
        )
        for condition in conditions
    ]
    _add_control_comparisons(condition_summaries)
    _add_study_set_metrics(condition_summaries, cases_path=cases_path)
    _add_metric_layer_summaries(condition_summaries)
    summary_json = output_dir / "layer_b_comparison_summary.json"
    summary_md = output_dir / "layer_b_comparison_summary.md"
    return {
        "summary": {
            "n_conditions": len(condition_summaries),
            "n_cases": sum(condition["n_cases"] for condition in condition_summaries),
            "status_counts": _status_counts(
                [
                    case
                    for condition in condition_summaries
                    for case in condition["cases"]
                ]
            ),
        },
        "conditions": condition_summaries,
        "case_index": _case_index(condition_summaries),
        "outputs": {
            "summary_json": str(summary_json),
            "summary_md": str(summary_md),
        },
        "postprocessing": {
            "normalize_artifacts": normalize_artifacts,
            "trace_br_anchors": trace_br_anchors,
        },
    }


def run_comparison(
    conditions: list[ConditionInput],
    output_dir: Path,
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    normalize_artifacts: bool = False,
    trace_br_anchors: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_summary(
        conditions,
        output_dir,
        cases_path=cases_path,
        normalize_artifacts=normalize_artifacts,
        trace_br_anchors=trace_br_anchors,
    )
    summary_json = output_dir / "layer_b_comparison_summary.json"
    summary_md = output_dir / "layer_b_comparison_summary.md"
    summary_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_md.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def parse_condition(value: str) -> ConditionInput:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--condition must use NAME=PATH")
    name, raw_path = value.split("=", maxsplit=1)
    name = name.strip()
    raw_path = raw_path.strip()
    if not name or not raw_path:
        raise argparse.ArgumentTypeError("--condition must use non-empty NAME=PATH")
    return ConditionInput(name=name, path=Path(raw_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-contract",
        action="store_true",
        help="Print the Layer B artifact/evaluator contract and exit.",
    )
    parser.add_argument(
        "--condition",
        action="append",
        nargs="+",
        required=False,
        metavar="NAME=PATH",
        help="Layer B artifact condition to compare. Repeat or pass multiple values.",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--normalize-artifacts",
        action="store_true",
        help="Write normalized per-case coordinate/study artifacts and include their summary.",
    )
    parser.add_argument(
        "--trace-br-anchors",
        action="store_true",
        help="Write per-case BR anchor traces and include anchor-use summaries.",
    )
    args = parser.parse_args(argv)
    if args.print_contract:
        print(json.dumps(layer_b_contract(), indent=2, sort_keys=True))
        return 0
    if not args.condition:
        parser.error("--condition is required unless --print-contract is used")
    if args.output_dir is None:
        parser.error("--output-dir is required unless --print-contract is used")

    conditions = [
        parse_condition(value)
        for condition_group in args.condition
        for value in condition_group
    ]
    payload = run_comparison(
        conditions,
        args.output_dir,
        cases_path=args.cases,
        normalize_artifacts=args.normalize_artifacts,
        trace_br_anchors=args.trace_br_anchors,
    )
    print(json.dumps({"summary": payload["summary"], "outputs": payload["outputs"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
