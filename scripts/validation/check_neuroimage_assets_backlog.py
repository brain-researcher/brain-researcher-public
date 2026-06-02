#!/usr/bin/env python3
"""Validate the neuroimage asset backlog registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "configs" / "br-kg" / "neuroimage_assets_backlog.yaml"

REQUIRED_FAMILY_STATES = {
    "already_usable",
    "present_not_standardized",
    "missing_and_should_acquire",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("registry root must be a mapping")
    return payload


def _validate_registry(path: Path, check_paths: bool) -> dict[str, Any]:
    payload = _load_yaml(path)
    row_model = payload.get("row_model") or {}
    required_fields = set(row_model.get("required_fields") or [])
    current_state_values = set(row_model.get("current_state_values") or [])
    local_status_values = set(row_model.get("local_status_values") or [])
    resolver_status_values = set(row_model.get("resolver_status_values") or [])
    provenance_status_values = set(row_model.get("provenance_status_values") or [])
    license_status_values = set(row_model.get("license_status_values") or [])
    priority_values = set(row_model.get("priority_values") or [])

    errors: list[str] = []
    families = payload.get("families")
    decision = payload.get("decision") or {}
    template_decision = decision.get("standardized_templates") or {}

    if payload.get("version") != "1.0":
        errors.append("version must be 1.0")
    if not families or not isinstance(families, list):
        errors.append("families must be a non-empty list")
    if template_decision.get("answer") != "partial_yes":
        errors.append("decision.standardized_templates.answer must be partial_yes")

    summary = {
        "valid_registry": False,
        "registry_path": str(path),
        "family_count": 0,
        "entry_count": 0,
        "already_usable_count": 0,
        "present_not_standardized_count": 0,
        "missing_and_should_acquire_count": 0,
        "check_paths": check_paths,
    }

    if errors:
        return {"summary": summary, "validation_errors": errors}

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

        seen_states: set[str] = set()
        summary["family_count"] += 1

        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"{family_id} contains a non-mapping entry")
                continue

            missing_fields = sorted(required_fields - set(entry.keys()))
            if missing_fields:
                errors.append(
                    f"{family_id}/{entry.get('asset_name', 'unknown_asset')} missing fields: {', '.join(missing_fields)}"
                )
                continue

            current_state = entry["current_state"]
            local_status = entry["local_status"]
            resolver_status = entry["resolver_status"]
            provenance_status = entry["provenance_status"]
            license_status = entry["license_status"]
            priority = entry["priority"]
            evidence_paths = entry["evidence_paths"]

            if current_state not in current_state_values:
                errors.append(f"{family_id}/{entry['asset_name']} invalid current_state={current_state}")
            if local_status not in local_status_values:
                errors.append(f"{family_id}/{entry['asset_name']} invalid local_status={local_status}")
            if resolver_status not in resolver_status_values:
                errors.append(f"{family_id}/{entry['asset_name']} invalid resolver_status={resolver_status}")
            if provenance_status not in provenance_status_values:
                errors.append(
                    f"{family_id}/{entry['asset_name']} invalid provenance_status={provenance_status}"
                )
            if license_status not in license_status_values:
                errors.append(f"{family_id}/{entry['asset_name']} invalid license_status={license_status}")
            if priority not in priority_values:
                errors.append(f"{family_id}/{entry['asset_name']} invalid priority={priority}")
            if not isinstance(evidence_paths, list) or not evidence_paths:
                errors.append(f"{family_id}/{entry['asset_name']} evidence_paths must be a non-empty list")
            elif check_paths:
                for rel_path in evidence_paths:
                    candidate = ROOT / str(rel_path)
                    if not candidate.exists():
                        errors.append(
                            f"{family_id}/{entry['asset_name']} evidence path does not exist: {rel_path}"
                        )

            seen_states.add(current_state)
            summary["entry_count"] += 1
            summary[f"{current_state}_count"] += 1

        missing_states = REQUIRED_FAMILY_STATES - seen_states
        if missing_states:
            errors.append(
                f"{family_id} is missing current_state coverage for: {', '.join(sorted(missing_states))}"
            )

    summary["valid_registry"] = not errors
    return {"summary": summary, "validation_errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Path to the neuroimage asset backlog registry YAML.",
    )
    parser.add_argument(
        "--skip-path-check",
        action="store_true",
        help="Skip checking that evidence_paths exist on disk.",
    )
    args = parser.parse_args()

    result = _validate_registry(args.registry.resolve(), check_paths=not args.skip_path_check)
    print(json.dumps(result, indent=2))
    return 0 if result["summary"]["valid_registry"] else 1


if __name__ == "__main__":
    sys.exit(main())
