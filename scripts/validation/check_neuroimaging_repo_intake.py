#!/usr/bin/env python3
"""Validate the neuroimaging workflow repo-intake registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "configs" / "workflows" / "neuroimaging_repo_intake.yaml"

REQUIRED_STATES = {
    "already_usable",
    "present_not_standardized",
    "missing_and_should_acquire",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("registry root must be a mapping")
    return payload


def _validate_registry(path: Path) -> dict[str, Any]:
    payload = _load_yaml(path)
    row_model = payload.get("row_model") or {}
    required_fields = set(row_model.get("required_fields") or [])
    current_state_values = set(row_model.get("current_state_values") or [])
    packaging_mode_values = set(row_model.get("packaging_mode_values") or [])
    interface_mode_values = set(row_model.get("interface_mode_values") or [])
    runtime_status_values = set(row_model.get("runtime_status_values") or [])
    license_status_values = set(row_model.get("license_status_values") or [])
    priority_values = set(row_model.get("priority_values") or [])

    errors: list[str] = []
    families = payload.get("families")
    decision = (payload.get("decision") or {}).get("preproc_qc_first") or {}

    summary = {
        "valid_registry": False,
        "registry_path": str(path),
        "family_count": 0,
        "entry_count": 0,
        "already_usable_count": 0,
        "present_not_standardized_count": 0,
        "missing_and_should_acquire_count": 0,
    }

    if payload.get("version") != "1.0":
        errors.append("version must be 1.0")
    if decision.get("answer") is not True and decision.get("answer") != "yes":
        errors.append("decision.preproc_qc_first.answer must be yes")
    if not families or not isinstance(families, list):
        errors.append("families must be a non-empty list")
    if errors:
        return {"summary": summary, "validation_errors": errors}

    seen_states: set[str] = set()
    for family in families:
        if not isinstance(family, dict):
            errors.append("family entries must be mappings")
            continue
        family_id = family.get("family_id")
        entries = family.get("entries")
        if not isinstance(family_id, str) or not family_id:
            errors.append("family_id must be a non-empty string")
        if not isinstance(entries, list) or not entries:
            errors.append(f"{family_id or 'unknown_family'} entries must be a non-empty list")
            continue

        summary["family_count"] += 1
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"{family_id} contains a non-mapping entry")
                continue
            missing_fields = sorted(required_fields - set(entry.keys()))
            if missing_fields:
                errors.append(
                    f"{family_id}/{entry.get('repo_slug', 'unknown_repo')} missing fields: {', '.join(missing_fields)}"
                )
                continue

            current_state = entry["current_state"]
            packaging_mode = entry["packaging_mode"]
            interface_mode = entry["interface_mode"]
            runtime_status = entry["runtime_status"]
            license_status = entry["license_status"]
            priority = entry["priority"]
            evidence_urls = entry["evidence_urls"]

            if current_state not in current_state_values:
                errors.append(f"{family_id}/{entry['repo_slug']} invalid current_state={current_state}")
            if packaging_mode not in packaging_mode_values:
                errors.append(f"{family_id}/{entry['repo_slug']} invalid packaging_mode={packaging_mode}")
            if interface_mode not in interface_mode_values:
                errors.append(f"{family_id}/{entry['repo_slug']} invalid interface_mode={interface_mode}")
            if runtime_status not in runtime_status_values:
                errors.append(f"{family_id}/{entry['repo_slug']} invalid runtime_status={runtime_status}")
            if license_status not in license_status_values:
                errors.append(f"{family_id}/{entry['repo_slug']} invalid license_status={license_status}")
            if priority not in priority_values:
                errors.append(f"{family_id}/{entry['repo_slug']} invalid priority={priority}")
            if not isinstance(evidence_urls, list) or not evidence_urls:
                errors.append(f"{family_id}/{entry['repo_slug']} evidence_urls must be a non-empty list")
            elif not all(isinstance(url, str) and url.strip() for url in evidence_urls):
                errors.append(f"{family_id}/{entry['repo_slug']} evidence_urls must contain non-empty strings")

            seen_states.add(current_state)
            summary["entry_count"] += 1
            summary[f"{current_state}_count"] += 1

    missing_states = REQUIRED_STATES - seen_states
    if missing_states:
        errors.append(
            "registry is missing current_state coverage for: "
            + ", ".join(sorted(missing_states))
        )

    summary["valid_registry"] = not errors
    return {"summary": summary, "validation_errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Path to the neuroimaging workflow repo-intake YAML.",
    )
    args = parser.parse_args()

    result = _validate_registry(args.registry.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["summary"]["valid_registry"] else 1


if __name__ == "__main__":
    sys.exit(main())
