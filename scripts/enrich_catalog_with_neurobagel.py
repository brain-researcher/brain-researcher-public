#!/usr/bin/env python3
"""Enrich dataset catalog JSONL with Neurobagel TSV cohort annotations.

This script updates catalog rows in-place (or to a new file) by aggregating
dataset-level phenotype labels from a Neurobagel-style TSV.

Output fields:
  - subject_labels: list[str]
  - phenotype_summary: list[object]
    - includes `total_observations` (row-level count)
    - includes `unique_subjects` when participant identifiers are available
  - annotation_sources: list[str]
  - annotation_updated_at: ISO timestamp

Compatibility fields are also updated:
  - disease_flags
  - tags
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

DATASET_KEY_CANDIDATES = [
    "dataset_id",
    "dataset",
    "dataset_name",
    "datasetlabel",
    "dataset_label",
    "datasetname",
    "openneuro_id",
    "openneuro",
    "study_id",
    "study",
    "study_name",
    "studyid",
    "studyname",
    "source_repo_id",
    "accession",
    "DatasetName",
    "OpenNeuroID",
]

SUBJECT_META_KEYS = {
    "participant_id",
    "participant",
    "subject_id",
    "subject",
    "sub",
    "session_id",
    "session",
    "record_id",
    "node",
    "node_name",
    "site",
}

SUBJECT_ID_KEY_CANDIDATES = [
    "participant_id",
    "participant",
    "subject_id",
    "subject",
    "sub",
    "participantid",
    "subjectid",
]

CATEGORY_KEYWORDS = {
    "diagnosis": ("diagnos", "disease", "condition", "disorder"),
    "group": ("group", "cohort", "arm"),
    "demographics": ("age", "sex", "gender", "handed", "ethnic", "race"),
    "clinical": ("severity", "score", "symptom", "scale", "clinical"),
}

NON_DISEASE_LABELS = {
    "control",
    "controls",
    "healthy",
    "health",
    "patient",
    "patients",
    "case",
    "cases",
    "unknown",
    "n/a",
    "na",
    "none",
}


@dataclass
class ColumnAggregate:
    """Running aggregates for one phenotype column."""

    column: str
    name: str
    category: str
    total_observations: int = 0
    value_counts: Counter[str] = field(default_factory=Counter)
    numeric_values: list[float] = field(default_factory=list)
    unique_subject_ids: set[str] = field(default_factory=set)

    def add(self, raw_value: str, subject_id: str | None = None) -> None:
        value = _clean_value(raw_value)
        if not value:
            return
        self.total_observations += 1
        if subject_id:
            self.unique_subject_ids.add(subject_id)
        num = _to_float(value)
        if num is not None:
            self.numeric_values.append(num)
            return
        self.value_counts[value] += 1


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    return text


def _normalize_col_name(name: str) -> str:
    text = name.strip()
    text = re.sub(r"^(pheno_|phenotype_)", "", text, flags=re.IGNORECASE)
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.title() if text else name


def _to_float(value: str) -> float | None:
    try:
        parsed = float(value)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug


def _extract_openneuro_accession(value: str) -> str | None:
    if not value:
        return None
    match = re.search(r"(ds\d{6})", value.lower())
    if match:
        return match.group(1)
    return None


def _catalog_lookup_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()

    def add_value(value: Any) -> None:
        if not value:
            return
        text = str(value).strip().lower()
        if not text:
            return
        keys.add(text)
        accession = _extract_openneuro_accession(text)
        if accession:
            keys.add(accession)
            keys.add(f"ds:openneuro:{accession}")

    add_value(row.get("dataset_id"))
    add_value(row.get("source_repo_id"))
    for alias in row.get("alias") or []:
        add_value(alias)
    return keys


def _infer_category(column_name: str) -> str:
    lower = column_name.lower()
    for category, terms in CATEGORY_KEYWORDS.items():
        if any(term in lower for term in terms):
            return category
    return "phenotype"


def _find_dataset_keys(fieldnames: Iterable[str]) -> list[str]:
    normalized = {name.lower().strip(): name for name in fieldnames}
    keys: list[str] = []
    for candidate in DATASET_KEY_CANDIDATES:
        match = normalized.get(candidate.lower())
        if match:
            keys.append(match)
    return keys


def _find_subject_id_keys(fieldnames: Iterable[str]) -> list[str]:
    normalized = {name.lower().strip(): name for name in fieldnames}
    keys: list[str] = []
    for candidate in SUBJECT_ID_KEY_CANDIDATES:
        match = normalized.get(candidate.lower())
        if match and match not in keys:
            keys.append(match)
    return keys


def _select_phenotype_columns(
    fieldnames: Iterable[str], dataset_keys: set[str]
) -> list[str]:
    all_cols = list(fieldnames)
    selected: list[str] = []
    priority: list[str] = []

    for col in all_cols:
        col_l = col.lower().strip()
        if col in dataset_keys:
            continue
        if col_l in SUBJECT_META_KEYS:
            continue
        if col_l.endswith("_id") and not col_l.startswith(("pheno_", "phenotype_")):
            continue
        if col_l.startswith(("path_", "uri_", "url_")):
            continue
        if col_l.startswith(("pheno_", "phenotype_")):
            priority.append(col)
            continue
        if any(
            term in col_l
            for term in (
                "diagnos",
                "disease",
                "condition",
                "group",
                "age",
                "sex",
                "gender",
            )
        ):
            priority.append(col)
            continue
        selected.append(col)

    if priority:
        merged = []
        seen = set()
        for col in priority + selected:
            if col not in seen:
                seen.add(col)
                merged.append(col)
        return merged
    return selected


def _dataset_refs_from_row(
    row: dict[str, Any], dataset_keys: Iterable[str]
) -> set[str]:
    refs: set[str] = set()
    for key in dataset_keys:
        value = _clean_value(row.get(key))
        if not value:
            continue
        lower = value.lower()
        refs.add(lower)
        accession = _extract_openneuro_accession(lower)
        if accession:
            refs.add(accession)
            refs.add(f"ds:openneuro:{accession}")
    return refs


def _subject_id_from_row(
    row: dict[str, Any], subject_id_keys: Iterable[str]
) -> str | None:
    for key in subject_id_keys:
        value = _clean_value(row.get(key))
        if value:
            return value.lower()
    return None


def _merge_string_list(existing: Any, additions: Iterable[str], mode: str) -> list[str]:
    existing_list = [str(v).strip() for v in (existing or []) if str(v).strip()]
    if mode == "replace":
        existing_list = []
    merged = list(dict.fromkeys(existing_list + [v for v in additions if v]))
    return merged


def _summary_from_column_agg(agg: ColumnAggregate) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "name": agg.name,
        "column": agg.column,
        "category": agg.category,
        "total_observations": agg.total_observations,
        "distinct_values": len(agg.value_counts),
        "measurement_type": (
            "numeric" if agg.numeric_values and not agg.value_counts else "categorical"
        ),
    }
    if agg.unique_subject_ids:
        summary["unique_subjects"] = len(agg.unique_subject_ids)
    if agg.value_counts:
        summary["value_counts"] = dict(agg.value_counts.most_common(50))
    if agg.numeric_values:
        sorted_vals = sorted(agg.numeric_values)
        summary["numeric_summary"] = {
            "min": min(sorted_vals),
            "max": max(sorted_vals),
            "mean": statistics.fmean(sorted_vals),
            "median": statistics.median(sorted_vals),
        }
    return summary


def _build_subject_labels(phenotype_summary: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    seen = set()
    for item in phenotype_summary:
        name = str(item.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            labels.append(name)
        category = str(item.get("category") or "").lower()
        if category in {"diagnosis", "group", "clinical"}:
            value_counts = item.get("value_counts")
            if isinstance(value_counts, dict):
                for value in list(value_counts.keys())[:12]:
                    label = f"{name}={value}"
                    if label not in seen:
                        seen.add(label)
                        labels.append(label)
    return labels[:80]


def _infer_disease_flags(phenotype_summary: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    seen = set()
    for item in phenotype_summary:
        category = str(item.get("category") or "").lower()
        if category not in {"diagnosis", "group", "clinical"}:
            continue
        value_counts = item.get("value_counts")
        if isinstance(value_counts, dict):
            for raw in value_counts.keys():
                val = str(raw).strip()
                if not val:
                    continue
                if val.lower() in NON_DISEASE_LABELS:
                    continue
                if val not in seen:
                    seen.add(val)
                    flags.append(val)
    return flags[:40]


def _compatibility_tags(subject_labels: list[str]) -> list[str]:
    tags = ["neurobagel"]
    for label in subject_labels[:12]:
        slug = _slugify(label)
        if slug:
            tags.append(f"pheno:{slug}")
    return list(dict.fromkeys(tags))


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows


def _write_catalog(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def enrich_catalog(
    catalog_rows: list[dict[str, Any]],
    tsv_rows: Iterable[dict[str, Any]],
    fieldnames: list[str],
    *,
    mode: str = "append",
    annotation_source: str = "neurobagel_tsv",
    strict: bool = False,
) -> dict[str, Any]:
    index: dict[str, set[int]] = defaultdict(set)
    for idx, row in enumerate(catalog_rows):
        for key in _catalog_lookup_keys(row):
            index[key].add(idx)

    dataset_keys = _find_dataset_keys(fieldnames)
    if not dataset_keys:
        raise ValueError(
            f"No dataset key columns found. Tried: {', '.join(DATASET_KEY_CANDIDATES)}"
        )
    subject_id_keys = _find_subject_id_keys(fieldnames)
    phenotype_cols = _select_phenotype_columns(fieldnames, set(dataset_keys))
    if not phenotype_cols:
        raise ValueError(
            "No phenotype columns found in TSV after filtering metadata columns"
        )

    aggregates: dict[int, dict[str, ColumnAggregate]] = defaultdict(dict)
    unmatched_refs: Counter[str] = Counter()
    rows_total = 0
    matched_rows = 0

    for row in tsv_rows:
        rows_total += 1
        refs = _dataset_refs_from_row(row, dataset_keys)
        subject_id = _subject_id_from_row(row, subject_id_keys)
        if not refs:
            continue
        matched_indices: set[int] = set()
        for ref in refs:
            matched_indices.update(index.get(ref, set()))
        if not matched_indices:
            for ref in refs:
                unmatched_refs[ref] += 1
            continue

        matched_rows += 1
        for idx in matched_indices:
            by_col = aggregates[idx]
            for col in phenotype_cols:
                if col not in by_col:
                    by_col[col] = ColumnAggregate(
                        column=col,
                        name=_normalize_col_name(col),
                        category=_infer_category(col),
                    )
                by_col[col].add(_clean_value(row.get(col)), subject_id=subject_id)

    if strict and unmatched_refs:
        top = ", ".join(f"{k} ({v})" for k, v in unmatched_refs.most_common(10))
        raise ValueError(f"Unmatched dataset refs in TSV: {top}")

    now_iso = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    updated_rows = 0

    for idx, col_aggs in aggregates.items():
        summaries = [
            _summary_from_column_agg(agg)
            for agg in sorted(col_aggs.values(), key=lambda item: item.name.lower())
            if agg.total_observations > 0
        ]
        if not summaries:
            continue

        subject_labels = _build_subject_labels(summaries)
        disease_flags_new = _infer_disease_flags(summaries)
        tags_new = _compatibility_tags(subject_labels)

        row = catalog_rows[idx]
        existing_summary = row.get("phenotype_summary")
        if mode == "append" and isinstance(existing_summary, list):
            merged_by_name: dict[str, dict[str, Any]] = {}
            for item in existing_summary:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("column") or item.get("name") or "").strip()
                if key:
                    merged_by_name[key] = item
            for item in summaries:
                key = str(item.get("column") or item.get("name") or "").strip()
                if key:
                    merged_by_name[key] = item
            summaries = sorted(
                merged_by_name.values(), key=lambda x: str(x.get("name", "")).lower()
            )

        row["subject_labels"] = _merge_string_list(
            row.get("subject_labels"), subject_labels, mode
        )
        row["phenotype_summary"] = summaries
        row["annotation_sources"] = _merge_string_list(
            row.get("annotation_sources"), [annotation_source], mode
        )
        row["annotation_updated_at"] = now_iso
        row["disease_flags"] = _merge_string_list(
            row.get("disease_flags"), disease_flags_new, mode
        )
        row["tags"] = _merge_string_list(row.get("tags"), tags_new, mode)
        updated_rows += 1

    return {
        "rows_total": rows_total,
        "matched_rows": matched_rows,
        "updated_rows": updated_rows,
        "unmatched_dataset_refs": unmatched_refs,
        "dataset_key_columns": dataset_keys,
        "subject_id_columns": subject_id_keys,
        "phenotype_columns": phenotype_cols,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich dataset catalog JSONL with Neurobagel TSV annotations."
    )
    parser.add_argument(
        "--catalog-in",
        type=Path,
        default=Path("configs/datasets/catalog.v1.jsonl"),
        help="Input dataset catalog JSONL path.",
    )
    parser.add_argument(
        "--catalog-out",
        type=Path,
        default=None,
        help="Output catalog JSONL path (default: overwrite --catalog-in).",
    )
    parser.add_argument(
        "--neurobagel-tsv",
        type=Path,
        required=True,
        help="Path to Neurobagel TSV file.",
    )
    parser.add_argument(
        "--mode",
        choices=("append", "replace"),
        default="append",
        help="Append or replace managed annotation fields.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when TSV contains dataset references that do not match the catalog.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and aggregate only; do not write output file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog_in = args.catalog_in
    catalog_out = args.catalog_out or catalog_in
    neurobagel_tsv = args.neurobagel_tsv

    if not catalog_in.exists():
        raise SystemExit(f"Catalog file not found: {catalog_in}")
    if not neurobagel_tsv.exists():
        raise SystemExit(f"TSV file not found: {neurobagel_tsv}")

    catalog_rows = _load_catalog(catalog_in)
    with neurobagel_tsv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise SystemExit("TSV has no header row")
        stats = enrich_catalog(
            catalog_rows,
            reader,
            reader.fieldnames,
            mode=args.mode,
            annotation_source=f"neurobagel_tsv:{neurobagel_tsv.name}",
            strict=args.strict,
        )

    print(f"Catalog rows: {len(catalog_rows)}")
    print(f"TSV rows processed: {stats['rows_total']}")
    print(f"TSV rows matched to catalog: {stats['matched_rows']}")
    print(f"Catalog rows updated: {stats['updated_rows']}")
    print(f"Dataset key columns: {', '.join(stats['dataset_key_columns'])}")
    print(
        "Subject id columns used: "
        + (
            ", ".join(stats["subject_id_columns"])
            if stats["subject_id_columns"]
            else "(none)"
        )
    )
    print(f"Phenotype columns used: {', '.join(stats['phenotype_columns'])}")
    unmatched = stats["unmatched_dataset_refs"]
    if unmatched:
        top = ", ".join(f"{key} ({count})" for key, count in unmatched.most_common(10))
        print(f"Unmatched dataset refs (top): {top}")

    if args.dry_run:
        print("Dry-run mode: no output file written.")
        return 0

    _write_catalog(catalog_out, catalog_rows)
    print(f"Wrote enriched catalog: {catalog_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
