#!/usr/bin/env python3
"""Harness-owned Layer B provenance, report, and artifact preflight finalizer."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.neurometabench_v1.layer_b_br_anchor_tracer import trace_case_br_anchors

PROVENANCE_REQUIRED_FIELDS = (
    "condition_id",
    "runner",
    "model_target",
    "br_mode",
    "source_assets_used",
    "commands_executed",
    "start_timestamp",
    "end_timestamp",
    "repository_commit",
)
BR_REQUIRED_MODES = {
    "with_br_required",
    "br_required_preflight",
    "br_required_reconciliation",
    "br_required_audit_only",
}
COORDINATE_FIELD_ALIASES = {
    "x": ("x", "X", "coord_x", "x_coord", "x_mni", "mni_x", "x_tal", "talairach_x"),
    "y": ("y", "Y", "coord_y", "y_coord", "y_mni", "mni_y", "y_tal", "talairach_y"),
    "z": ("z", "Z", "coord_z", "z_coord", "z_mni", "mni_z", "z_tal", "talairach_z"),
}
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


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def _source_assets_from_input_manifest(input_manifest: dict[str, Any]) -> list[str]:
    assets = input_manifest.get("nimads_assets")
    out: list[str] = []
    if isinstance(assets, dict):
        for value in assets.values():
            if isinstance(value, str) and value:
                out.append(value)
            elif isinstance(value, list):
                out.extend(str(item) for item in value if str(item))
    return sorted(dict.fromkeys(out))


def _count_csv_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _row in csv.DictReader(handle))
    except csv.Error:
        return None


def _coordinate_parseable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except csv.Error:
        return False
    if not rows:
        return False
    for row in rows:
        try:
            for aliases in COORDINATE_FIELD_ALIASES.values():
                value = next(
                    ((row.get(alias) or "").strip() for alias in aliases if (row.get(alias) or "").strip()),
                    "",
                )
                float(value)
        except ValueError:
            return False
    return True


def _map_paths(case_dir: Path) -> list[Path]:
    maps_dir = case_dir / "ale_maps"
    if not maps_dir.exists():
        return []
    return sorted(
        path
        for path in maps_dir.rglob("*")
        if path.name.endswith(".nii") or path.name.endswith(".nii.gz")
    )


def _nifti_load_check(map_paths: list[Path]) -> dict[str, Any]:
    if not map_paths:
        return {"pass": False, "reason": "missing_ale_map_artifact", "paths": []}
    try:
        import nibabel as nib
    except Exception as exc:  # pragma: no cover - environment dependent
        return {
            "pass": None,
            "reason": f"nibabel_unavailable:{type(exc).__name__}",
            "paths": [str(path) for path in map_paths],
        }
    errors: list[str] = []
    for path in map_paths:
        try:
            nib.load(str(path))
        except Exception as exc:  # pragma: no cover - depends on NIfTI fixtures
            errors.append(f"{path.name}:{type(exc).__name__}")
    return {
        "pass": not errors,
        "reason": ";".join(errors) if errors else None,
        "paths": [str(path) for path in map_paths],
    }


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


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _fallback_map_evidence(
    *,
    case_dir: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    source_texts: list[tuple[str, str]] = []
    structured_matches: list[dict[str, Any]] = []
    nonfallback_sources: list[dict[str, Any]] = []
    for name in (
        "metrics.json",
        "provenance_manifest.json",
        "spatial_report.md",
        "trajectory.json",
        "observation.json",
        "failure.json",
        "RUN_SUMMARY.json",
    ):
        path = case_dir / name
        if name in {"metrics.json", "provenance_manifest.json"}:
            data = _read_json(path)
            decision = _structured_fallback_map_decision(data) if data else None
            if decision is not None:
                entry = {"source": str(path), "terms": decision["terms"], "kind": "structured"}
                if decision["detected"]:
                    structured_matches.append(entry)
                else:
                    nonfallback_sources.append(entry)
                continue
        text = _fallback_scan_text_for_json_file(path) if name.endswith(".json") else _read_text(path)
        if text:
            source_texts.append((str(path), text))
    if provenance:
        decision = _structured_fallback_map_decision(provenance)
        if decision is not None:
            entry = {
                "source": "provenance_manifest:merged",
                "terms": decision["terms"],
                "kind": "structured",
            }
            if decision["detected"]:
                structured_matches.append(entry)
            else:
                nonfallback_sources.append(entry)
        else:
            source_texts.append(
                (
                    "provenance_manifest:merged",
                    json.dumps(
                        _scrub_promptish_json_for_fallback_scan(provenance),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            )

    matches: list[dict[str, Any]] = list(structured_matches)
    for source, text in source_texts:
        terms = _fallback_map_terms(text)
        if terms:
            matches.append({"source": source, "terms": terms})

    detected = bool(matches)
    return {
        "pass": not detected,
        "detected": detected,
        "reason": "degraded_fallback_map_evidence" if detected else None,
        "matches": matches,
        "structured_nonfallback": nonfallback_sources,
    }


def _report_mentions(
    *,
    report_text: str,
    n_coordinate_rows: int | None,
    n_included_studies: int | None,
    map_paths: list[Path],
) -> dict[str, bool]:
    lower = report_text.lower()
    return {
        "mentions_ale": "ale" in lower,
        "mentions_coordinate_count": (
            n_coordinate_rows is not None and str(n_coordinate_rows) in report_text
        ),
        "mentions_study_count": (
            n_included_studies is not None and str(n_included_studies) in report_text
        ),
        "mentions_map_output_path": any(path.name in report_text for path in map_paths),
    }


def _render_report(
    *,
    case_id: str | None,
    meta_pmid: str,
    n_coordinate_rows: int | None,
    n_included_studies: int | None,
    map_paths: list[Path],
    preflight_reasons: list[str],
) -> str:
    map_lines = "\n".join(f"- `{path}`" for path in map_paths) or "- none"
    reasons = "\n".join(f"- {reason}" for reason in preflight_reasons) or "- none"
    return f"""# Layer B Artifact Report

Case: `{case_id or f"neurometabench:{meta_pmid}"}`

This report was generated by the NeuroMetaBench harness finalizer from
discovered artifacts. It is a contract report, not a model-authored scientific
claim.

- ALE map generated: `{bool(map_paths)}`
- Coordinate rows: `{n_coordinate_rows if n_coordinate_rows is not None else "missing"}`
- Included study rows: `{n_included_studies if n_included_studies is not None else "missing"}`

ALE map outputs:

{map_lines}

Preflight issues:

{reasons}
"""


def _ensure_contract_report(
    *,
    report_path: Path,
    case_id: str | None,
    meta_pmid: str,
    n_coordinate_rows: int | None,
    n_included_studies: int | None,
    map_paths: list[Path],
    preflight_reasons: list[str],
    report_checks: dict[str, bool],
) -> None:
    harness_report = _render_report(
        case_id=case_id,
        meta_pmid=meta_pmid,
        n_coordinate_rows=n_coordinate_rows,
        n_included_studies=n_included_studies,
        map_paths=map_paths,
        preflight_reasons=preflight_reasons,
    )
    if not report_path.exists():
        report_path.write_text(harness_report, encoding="utf-8")
        return

    if all(report_checks.values()):
        return

    original = report_path.read_text(encoding="utf-8", errors="ignore")
    if "## Harness Contract Addendum" in original:
        return
    raw_path = report_path.with_name("spatial_report.agent_raw.md")
    if not raw_path.exists():
        raw_path.write_text(original, encoding="utf-8")
    report_path.write_text(
        f"{original.rstrip()}\n\n---\n\n## Harness Contract Addendum\n\n"
        f"{harness_report}",
        encoding="utf-8",
    )


def _merge_provenance(
    *,
    case_dir: Path,
    condition_metadata: dict[str, Any],
    input_manifest: dict[str, Any],
    command: list[str],
    started_at: str | None,
    ended_at: str | None,
    repo_root: Path,
) -> dict[str, Any]:
    path = case_dir / "provenance_manifest.json"
    existing = _read_json(path)
    if existing and not (case_dir / "provenance_manifest.agent_raw.json").exists():
        _write_json(case_dir / "provenance_manifest.agent_raw.json", existing)
    source_assets = _source_assets_from_input_manifest(input_manifest)
    harness_fields = {
        "condition_id": condition_metadata.get("condition_id"),
        "runner": condition_metadata.get("runner"),
        "model_target": condition_metadata.get("model_target"),
        "br_mode": condition_metadata.get("br_mode"),
        "source_assets_used": source_assets,
        "commands_executed": [" ".join(command)] if command else [],
        "start_timestamp": started_at,
        "end_timestamp": ended_at or utc_now(),
        "repository_commit": _git_commit(repo_root) or "unknown",
    }
    merged = dict(existing)
    injected: list[str] = []
    for key, value in harness_fields.items():
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
            injected.append(key)
    merged["harness_finalizer"] = {
        "applied": True,
        "injected_fields": injected,
        "raw_manifest_preserved": existing
        and (case_dir / "provenance_manifest.agent_raw.json").exists(),
    }
    _write_json(path, merged)
    return merged


def _preflight_case(
    *,
    case_dir: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    coordinate_table = case_dir / "coordinate_table.csv"
    included_studies = case_dir / "included_studies.csv"
    report_path = case_dir / "spatial_report.md"
    map_paths = _map_paths(case_dir)
    n_coordinate_rows = _count_csv_rows(coordinate_table)
    n_included_studies = _count_csv_rows(included_studies)
    map_load = _nifti_load_check(map_paths)
    fallback_map = _fallback_map_evidence(case_dir=case_dir, provenance=provenance)
    provenance_fields = {
        field: provenance.get(field) not in (None, "", [], {})
        for field in PROVENANCE_REQUIRED_FIELDS
    }
    report_text = report_path.read_text(encoding="utf-8", errors="ignore") if report_path.exists() else ""
    report_checks = _report_mentions(
        report_text=report_text,
        n_coordinate_rows=n_coordinate_rows,
        n_included_studies=n_included_studies,
        map_paths=map_paths,
    )
    checks = {
        "case_dir_exists": case_dir.exists(),
        "evaluator_discovery_hint": (case_dir / "metrics.json").exists(),
        "coordinate_table_exists": coordinate_table.exists(),
        "coordinate_table_parseable": _coordinate_parseable(coordinate_table),
        "included_studies_exists": included_studies.exists(),
        "ale_map_exists": bool(map_paths),
        "ale_map_loadable": map_load.get("pass"),
        "ale_map_not_degraded_fallback": fallback_map["pass"],
        "provenance_required_fields": all(provenance_fields.values()),
        "report_exists": report_path.exists(),
        "report_mentions_ale": report_checks["mentions_ale"],
        "report_mentions_coordinate_count": report_checks["mentions_coordinate_count"],
        "report_mentions_study_count": report_checks["mentions_study_count"],
        "report_mentions_map_output_path": report_checks["mentions_map_output_path"],
    }
    reasons = [key for key, value in checks.items() if value is not True]
    return {
        "status": "pass" if not reasons else "fail",
        "checks": checks,
        "failure_reasons": reasons,
        "n_coordinate_rows": n_coordinate_rows,
        "n_included_studies": n_included_studies,
        "map_load_check": map_load,
        "fallback_map_check": fallback_map,
        "provenance_required_fields": provenance_fields,
        "report_checks": report_checks,
    }


def finalize_layer_b_case(
    *,
    case_dir: Path,
    input_manifest_path: Path,
    condition_metadata: dict[str, Any],
    command: list[str],
    started_at: str | None,
    ended_at: str | None,
    repo_root: Path,
    episode_dir: Path | None = None,
    require_br_effective_use: bool = False,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    input_manifest = _read_json(input_manifest_path)
    meta_pmid = str(
        input_manifest.get("meta_pmid")
        or case_dir.name.replace("layer_b_", "").split("_", maxsplit=1)[0]
    )
    case_id = str(input_manifest.get("case_id") or f"neurometabench:{meta_pmid}")
    provenance = _merge_provenance(
        case_dir=case_dir,
        condition_metadata=condition_metadata,
        input_manifest=input_manifest,
        command=command,
        started_at=started_at,
        ended_at=ended_at,
        repo_root=repo_root,
    )
    initial_preflight = _preflight_case(case_dir=case_dir, provenance=provenance)
    report_path = case_dir / "spatial_report.md"
    _ensure_contract_report(
        report_path=report_path,
        case_id=case_id,
        meta_pmid=meta_pmid,
        n_coordinate_rows=initial_preflight["n_coordinate_rows"],
        n_included_studies=initial_preflight["n_included_studies"],
        map_paths=_map_paths(case_dir),
        preflight_reasons=initial_preflight["failure_reasons"],
        report_checks=initial_preflight["report_checks"],
    )
    preflight = _preflight_case(case_dir=case_dir, provenance=provenance)
    _write_json(case_dir / "artifact_preflight.json", preflight)
    br_trace = trace_case_br_anchors(
        case_dir,
        episode_dir=episode_dir,
        output_dir=case_dir,
    )
    br_mode = str(condition_metadata.get("br_mode") or "")
    br_required = require_br_effective_use or br_mode in BR_REQUIRED_MODES
    br_required_pass = (
        True if not br_required else br_trace["summary"]["br_effective_use_pass"]
    )
    summary = {
        "case_dir": str(case_dir),
        "input_manifest": str(input_manifest_path),
        "preflight_status": preflight["status"],
        "preflight_failure_reasons": preflight["failure_reasons"],
        "provenance_manifest": str(case_dir / "provenance_manifest.json"),
        "artifact_preflight": str(case_dir / "artifact_preflight.json"),
        "br_anchor_trace": str(case_dir / "br_anchor_trace.json"),
        "br_required": br_required,
        "br_required_pass": br_required_pass,
    }
    _write_json(case_dir / "harness_finalizer_summary.json", summary)
    return summary


def finalize_layer_b_episode(
    *,
    producer_output_dir: Path,
    input_root: Path,
    meta_pmids: list[str],
    condition_metadata: dict[str, Any],
    command: list[str],
    started_at: str | None,
    ended_at: str | None,
    repo_root: Path,
    episode_dir: Path | None = None,
    require_br_effective_use: bool = False,
) -> dict[str, Any]:
    cases = []
    for meta_pmid in meta_pmids:
        cases.append(
            finalize_layer_b_case(
                case_dir=producer_output_dir / f"layer_b_{meta_pmid}",
                input_manifest_path=input_root / f"layer_b_{meta_pmid}" / "input_manifest.json",
                condition_metadata=condition_metadata,
                command=command,
                started_at=started_at,
                ended_at=ended_at,
                repo_root=repo_root,
                episode_dir=episode_dir,
                require_br_effective_use=require_br_effective_use,
            )
        )
    summary = {
        "n_cases": len(cases),
        "cases": cases,
        "all_preflight_pass": all(case["preflight_status"] == "pass" for case in cases),
        "all_br_required_pass": all(case["br_required_pass"] for case in cases),
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-output-dir", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--meta-pmid", action="append", required=True)
    parser.add_argument("--condition-metadata", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--episode-dir", type=Path)
    parser.add_argument("--require-br-effective-use", action="store_true")
    args = parser.parse_args(argv)

    metadata = _read_json(args.condition_metadata)
    payload = finalize_layer_b_episode(
        producer_output_dir=args.producer_output_dir,
        input_root=args.input_root,
        meta_pmids=[str(value) for value in args.meta_pmid],
        condition_metadata=metadata,
        command=[],
        started_at=None,
        ended_at=utc_now(),
        repo_root=args.repo_root,
        episode_dir=args.episode_dir,
        require_br_effective_use=args.require_br_effective_use,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
