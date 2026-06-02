#!/usr/bin/env python3
"""Normalize NeuroMetaBench Layer B artifacts without overwriting raw outputs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

CANONICAL_COORDINATE_FIELDS = (
    "study_id",
    "analysis_id",
    "x",
    "y",
    "z",
    "space",
    "source_space",
    "source_asset",
    "source_file",
    "original_study_ids",
    "raw_row_index",
)
CANONICAL_STUDY_FIELDS = (
    "study_id",
    "study_pmid",
    "doi",
    "pmcid",
    "source_asset",
    "source_file",
    "sample_size",
    "original_study_ids",
    "raw_row_index",
)
COORDINATE_TABLE = "coordinate_table.csv"
INCLUDED_STUDIES = "included_studies.csv"
NORMALIZED_COORDINATE_TABLE = "coordinate_table.normalized.csv"
NORMALIZED_INCLUDED_STUDIES = "included_studies.normalized.csv"
NORMALIZATION_MANIFEST = "normalization_manifest.json"

PMID_TOKEN_RE = re.compile(r"\b\d{6,9}\b")
SPACE_ALIAS_NORMALIZATION = {
    "mni": "MNI",
    "mni152": "MNI",
    "mni152nlin6": "MNI",
    "mni152nlin2009casy": "MNI",
    "mnispace": "MNI",
    "mni1522mm": "MNI",
    "mni152_2mm": "MNI",
    "tal": "TAL",
    "talairach": "TAL",
    "talairachspace": "TAL",
}

COORDINATE_ALIASES = {
    "study_id": ("study_id", "study_name", "study", "study_label", "article_id"),
    "analysis_id": (
        "analysis_id",
        "analysis_name",
        "contrast_id",
        "contrast",
        "contrast_name",
        "condition_id",
    ),
    "x": (
        "x",
        "X",
        "coord_x",
        "x_coord",
        "x_mni",
        "mni_x",
        "x_tal",
        "talairach_x",
    ),
    "y": (
        "y",
        "Y",
        "coord_y",
        "y_coord",
        "y_mni",
        "mni_y",
        "y_tal",
        "talairach_y",
    ),
    "z": (
        "z",
        "Z",
        "coord_z",
        "z_coord",
        "z_mni",
        "mni_z",
        "z_tal",
        "talairach_z",
    ),
    "space": (
        "space",
        "coordinate_space",
        "coord_space",
        "atlas_space",
        "space_canonical",
    ),
    "source_space": (
        "source_space",
        "original_space",
        "reported_space",
        "space_original",
    ),
    "source_asset": (
        "source_asset",
        "source_project",
        "source_json",
        "source",
        "asset",
    ),
    "source_file": ("source_file", "file", "filename", "path"),
    "original_study_ids": (
        "original_study_ids",
        "source_study_ids",
        "study_match_key",
        "study_key",
    ),
}

STUDY_ALIASES = {
    "study_id": ("study_id", "study_name", "study", "study_label", "id", "article_id"),
    "study_pmid": ("study_pmid", "pmid", "PMID", "pubmed_id", "pubmed"),
    "doi": ("doi", "DOI"),
    "pmcid": ("pmcid", "PMCID", "pmc_id"),
    "source_asset": (
        "source_asset",
        "source_project",
        "source_json",
        "source",
        "asset",
    ),
    "source_file": ("source_file", "file", "filename", "path"),
    "sample_size": (
        "sample_size",
        "sample_sizes",
        "n",
        "n_subjects",
        "participants",
        "sample_size_min",
        "sample_size_max",
        "sample_size_mean",
    ),
    "original_study_ids": (
        "original_study_ids",
        "source_study_ids",
        "study_match_key",
        "study_key",
    ),
}


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _field_lookup(row: dict[str, str]) -> dict[str, str]:
    return {field.lower(): field for field in row}


def _first_value(
    row: dict[str, str],
    aliases: tuple[str, ...],
) -> tuple[str, str | None] | tuple[None, None]:
    lookup = _field_lookup(row)
    for alias in aliases:
        field = lookup.get(alias.lower())
        if field is None:
            continue
        value = (row.get(field) or "").strip()
        if value:
            return value, field
    return None, None


def _format_float(value: str | None) -> tuple[str, bool]:
    if value is None:
        return "", False
    try:
        number = float(value)
    except ValueError:
        return "", False
    if not math.isfinite(number):
        return "", False
    return f"{number:.6g}", True


def _normalize_space(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    key = re.sub(r"[^a-z0-9]+", "", text.lower())
    return SPACE_ALIAS_NORMALIZATION.get(key, text)


def _pmid_from_text(*values: str | None) -> str:
    for value in values:
        if not value:
            continue
        match = PMID_TOKEN_RE.search(value)
        if match:
            return match.group(0)
    return ""


def _coverage(rows: list[dict[str, str]], fields: tuple[str, ...]) -> float | None:
    if not rows:
        return None
    return sum(
        1
        for row in rows
        if any((row.get(field) or "").strip() for field in fields)
    ) / len(rows)


def _field_mapping_entry(
    *,
    canonical: str,
    source_field: str | None,
    inferred: bool = False,
) -> dict[str, Any]:
    return {
        "canonical": canonical,
        "source_field": source_field,
        "inferred": inferred,
    }


def _normalize_coordinate_rows(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    normalized: list[dict[str, str]] = []
    mappings: dict[str, set[str]] = {field: set() for field in CANONICAL_COORDINATE_FIELDS}
    repairs: list[dict[str, Any]] = []
    parseable = 0

    for index, row in enumerate(rows):
        out = {field: "" for field in CANONICAL_COORDINATE_FIELDS}
        for canonical, aliases in COORDINATE_ALIASES.items():
            value, source_field = _first_value(row, aliases)
            if value is not None:
                out[canonical] = value
            if source_field:
                mappings[canonical].add(source_field)

        for axis in ("x", "y", "z"):
            formatted, ok = _format_float(out[axis])
            out[axis] = formatted
            if not ok:
                repairs.append(
                    {
                        "row_index": index,
                        "field": axis,
                        "repair": "unparseable_coordinate_blank",
                    }
                )
        if out["x"] and out["y"] and out["z"]:
            parseable += 1

        raw_space = out["space"]
        canonical_space = _normalize_space(raw_space)
        if raw_space and canonical_space != raw_space:
            if not out["source_space"]:
                out["source_space"] = raw_space
            out["space"] = canonical_space
            repairs.append(
                {
                    "row_index": index,
                    "field": "space",
                    "repair": "canonicalized_coordinate_space_alias",
                    "raw_value": raw_space,
                    "canonical_value": canonical_space,
                }
            )
        if not out["space"] and out["source_space"]:
            inferred_space = _normalize_space(out["source_space"])
            if inferred_space:
                out["space"] = inferred_space
                repairs.append(
                    {
                        "row_index": index,
                        "field": "space",
                        "repair": "inferred_coordinate_space_from_source_space",
                        "raw_value": out["source_space"],
                        "canonical_value": inferred_space,
                    }
                )

        if not out["original_study_ids"] and out["study_id"]:
            out["original_study_ids"] = out["study_id"]
            repairs.append(
                {
                    "row_index": index,
                    "field": "original_study_ids",
                    "repair": "copied_from_study_id",
                }
            )
        if not out["analysis_id"]:
            out["analysis_id"] = f"analysis_{index + 1}"
            repairs.append(
                {
                    "row_index": index,
                    "field": "analysis_id",
                    "repair": "generated_stable_row_analysis_id",
                }
            )
        out["raw_row_index"] = str(index)
        normalized.append(out)

    mapping_rows = [
        _field_mapping_entry(
            canonical=field,
            source_field="|".join(sorted(source_fields)) if source_fields else None,
        )
        for field, source_fields in mappings.items()
    ]
    return normalized, {
        "row_count": len(rows),
        "parseable_coordinate_rows": parseable,
        "coordinate_parseability": parseable / len(rows) if rows else None,
        "field_mappings": mapping_rows,
        "repairs": repairs,
    }


def _normalize_study_rows(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    normalized: list[dict[str, str]] = []
    mappings: dict[str, set[str]] = {field: set() for field in CANONICAL_STUDY_FIELDS}
    repairs: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        out = {field: "" for field in CANONICAL_STUDY_FIELDS}
        for canonical, aliases in STUDY_ALIASES.items():
            value, source_field = _first_value(row, aliases)
            if value is not None:
                out[canonical] = value
            if source_field:
                mappings[canonical].add(source_field)

        if not out["original_study_ids"] and out["study_id"]:
            out["original_study_ids"] = out["study_id"]
            repairs.append(
                {
                    "row_index": index,
                    "field": "original_study_ids",
                    "repair": "copied_from_study_id",
                }
            )
        inferred_pmid = _pmid_from_text(out["study_id"], out["original_study_ids"])
        if not out["study_pmid"] and inferred_pmid:
            out["study_pmid"] = inferred_pmid
            repairs.append(
                {
                    "row_index": index,
                    "field": "study_pmid",
                    "repair": "inferred_pmid_from_study_identifier",
                }
            )
        out["raw_row_index"] = str(index)
        normalized.append(out)

    mapping_rows = [
        _field_mapping_entry(
            canonical=field,
            source_field="|".join(sorted(source_fields)) if source_fields else None,
        )
        for field, source_fields in mappings.items()
    ]
    return normalized, {
        "row_count": len(rows),
        "public_identifier_coverage": _coverage(normalized, ("study_pmid", "doi", "pmcid")),
        "source_provenance_coverage": _coverage(
            normalized, ("source_asset", "source_file")
        ),
        "sample_size_coverage": _coverage(normalized, ("sample_size",)),
        "field_mappings": mapping_rows,
        "repairs": repairs,
    }


def normalize_case_bundle(
    case_dir: Path,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Write normalized artifacts for a single Layer B case directory."""

    case_dir = Path(case_dir)
    output_dir = output_dir or case_dir / "normalized_artifacts"
    coordinate_path = case_dir / COORDINATE_TABLE
    studies_path = case_dir / INCLUDED_STUDIES
    coordinate_fields, coordinate_rows = _read_csv(coordinate_path)
    study_fields, study_rows = _read_csv(studies_path)

    normalized_coordinates, coordinate_manifest = _normalize_coordinate_rows(
        coordinate_rows
    )
    normalized_studies, study_manifest = _normalize_study_rows(study_rows)

    normalized_coordinate_path = output_dir / NORMALIZED_COORDINATE_TABLE
    normalized_studies_path = output_dir / NORMALIZED_INCLUDED_STUDIES
    manifest_path = output_dir / NORMALIZATION_MANIFEST
    _write_csv(
        normalized_coordinate_path,
        CANONICAL_COORDINATE_FIELDS,
        normalized_coordinates,
    )
    _write_csv(
        normalized_studies_path,
        CANONICAL_STUDY_FIELDS,
        normalized_studies,
    )

    manifest = {
        "case_dir": str(case_dir),
        "output_dir": str(output_dir),
        "raw_contract": {
            "coordinate_table": {
                "present": coordinate_path.exists(),
                "path": str(coordinate_path),
                "fields": coordinate_fields,
                "row_count": len(coordinate_rows),
            },
            "included_studies": {
                "present": studies_path.exists(),
                "path": str(studies_path),
                "fields": study_fields,
                "row_count": len(study_rows),
            },
        },
        "normalized_contract": {
            "coordinate_table": {
                "path": str(normalized_coordinate_path),
                "fields": list(CANONICAL_COORDINATE_FIELDS),
                **coordinate_manifest,
            },
            "included_studies": {
                "path": str(normalized_studies_path),
                "fields": list(CANONICAL_STUDY_FIELDS),
                **study_manifest,
            },
        },
        "normalization_delta": {
            "coordinate_rows_changed": bool(coordinate_rows),
            "study_rows_changed": bool(study_rows),
            "n_repairs": len(coordinate_manifest["repairs"])
            + len(study_manifest["repairs"]),
            "raw_artifacts_overwritten": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    manifest = normalize_case_bundle(args.case_dir, output_dir=args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
