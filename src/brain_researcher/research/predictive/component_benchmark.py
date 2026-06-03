"""Helpers for a Liu-style ICA-component FC benchmark line."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


@dataclass(frozen=True)
class ComponentTarget:
    target_column: str
    display_name: str
    reference_mean_r: float
    reference_best_r: float
    notes: str = ""


def load_component_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"benchmark_name", "subject_id_column", "targets"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"Missing manifest keys: {missing}")
    if not isinstance(payload["targets"], list) or not payload["targets"]:
        raise ValueError("Manifest targets must be a non-empty list")
    return payload


def component_targets_from_manifest(manifest: dict[str, Any]) -> list[ComponentTarget]:
    targets: list[ComponentTarget] = []
    for entry in manifest["targets"]:
        targets.append(
            ComponentTarget(
                target_column=str(entry["target_column"]),
                display_name=str(entry.get("display_name") or entry["target_column"]),
                reference_mean_r=float(entry["reference_mean_r"]),
                reference_best_r=float(entry["reference_best_r"]),
                notes=str(entry.get("notes") or ""),
            )
        )
    return targets


def validate_component_csv(
    csv_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Component CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            raise ValueError(f"CSV has no header row: {csv_path}")
        row_count = sum(1 for _ in reader)

    subject_id_column = manifest["subject_id_column"]
    missing_columns = []
    if subject_id_column not in fieldnames:
        missing_columns.append(subject_id_column)

    for target in component_targets_from_manifest(manifest):
        if target.target_column not in fieldnames:
            missing_columns.append(target.target_column)

    if missing_columns:
        raise ValueError(
            f"Missing required columns in component CSV: {sorted(set(missing_columns))}"
        )

    return {
        "csv_path": str(csv_path),
        "row_count": row_count,
        "column_count": len(fieldnames),
        "fieldnames": fieldnames,
        "subject_id_column": subject_id_column,
        "target_columns": [
            target.target_column for target in component_targets_from_manifest(manifest)
        ],
        "sha256": _sha256(csv_path),
        "validated_at_utc": _utc_now(),
    }


def compute_component_line_score(
    ledger_path: Path,
    manifest: dict[str, Any],
    *,
    phase_name: str | None = None,
) -> dict[str, Any]:
    rows = _read_jsonl(ledger_path)
    component_targets = component_targets_from_manifest(manifest)
    phase_filter = phase_name or manifest.get("phase_name")

    target_summaries: list[dict[str, Any]] = []
    mean_ref_ratios: list[float] = []
    best_ref_ratios: list[float] = []

    for target in component_targets:
        target_rows = []
        for row in rows:
            if phase_filter and row.get("phase") != phase_filter:
                continue
            if row.get("config", {}).get("target") != target.target_column:
                continue
            target_rows.append(row)

        best_r = None
        best_r2 = None
        best_run_id = None
        primary_metric_names: set[str] = set()
        for row in target_rows:
            scores = row.get("scores", {})
            primary_metric = scores.get("primary_metric_name")
            if primary_metric:
                primary_metric_names.add(str(primary_metric))
            gold_r = scores.get("gold_r")
            gold_r2 = scores.get("gold_r2")
            if gold_r is None:
                continue
            gold_r = float(gold_r)
            if best_r is None or gold_r > best_r:
                best_r = gold_r
                best_run_id = row.get("run_id")
                best_r2 = None if gold_r2 is None else float(gold_r2)

        ratio_vs_mean = None if best_r is None else best_r / target.reference_mean_r
        ratio_vs_best = None if best_r is None else best_r / target.reference_best_r
        if ratio_vs_mean is not None:
            mean_ref_ratios.append(max(0.0, min(ratio_vs_mean, 1.0)))
        if ratio_vs_best is not None:
            best_ref_ratios.append(max(0.0, min(ratio_vs_best, 1.0)))

        target_summaries.append(
            {
                "target_column": target.target_column,
                "display_name": target.display_name,
                "run_count": len(target_rows),
                "best_gold_r": None if best_r is None else round(best_r, 6),
                "best_gold_r2": None if best_r2 is None else round(best_r2, 6),
                "reference_mean_r": target.reference_mean_r,
                "reference_best_r": target.reference_best_r,
                "ratio_vs_mean_reference": (
                    None if ratio_vs_mean is None else round(ratio_vs_mean, 4)
                ),
                "ratio_vs_best_reference": (
                    None if ratio_vs_best is None else round(ratio_vs_best, 4)
                ),
                "best_run_id": best_run_id,
                "primary_metric_names_seen": sorted(primary_metric_names),
                "notes": target.notes,
            }
        )

    coverage_fraction = len(
        [item for item in target_summaries if item["run_count"] > 0]
    ) / len(component_targets)
    score_vs_mean = coverage_fraction * (sum(mean_ref_ratios) / len(component_targets))
    score_vs_best = coverage_fraction * (sum(best_ref_ratios) / len(component_targets))

    return {
        "scorer_name": "predictive_liu_component_line",
        "scored_at_utc": _utc_now(),
        "ledger_path": str(ledger_path),
        "ledger_sha256": _sha256(ledger_path),
        "phase_name": phase_filter,
        "benchmark_name": manifest["benchmark_name"],
        "reference_type": manifest.get("reference_type", "pearson_r"),
        "primary_metric": manifest.get("primary_metric", "gold_r"),
        "coverage_fraction": round(coverage_fraction, 4),
        "score_vs_mean_reference": round(score_vs_mean, 4),
        "score_vs_best_reference": round(score_vs_best, 4),
        "score": round(score_vs_mean, 4),
        "contract_satisfied": all(item["run_count"] > 0 for item in target_summaries),
        "target_summaries": target_summaries,
    }
