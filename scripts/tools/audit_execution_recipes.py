#!/usr/bin/env python3
"""Audit execution-story coverage for exposed tools and workflows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.mcp.execution_recipes import resolve_recipe_metadata
from brain_researcher.services.tools.catalog_loader import (
    load_orchestration_workflows,
    load_tool_specs,
)
from brain_researcher.services.tools.spec import ToolSpec, infer_requires_runtime

_EXTERNAL_STEP_PREFIXES = (
    "run_",
    "container.",
    "bidsapp.",
    "python.fmriprep.",
    "python.mriqc.",
    "python.qsiprep.",
    "python.xcpd.",
    "fsl.",
    "fsl_",
    "afni.",
    "afni_",
    "ants.",
    "ants_",
    "mrtrix3.",
    "mrtrix3_",
)
_EXTERNAL_STEPS = {"run_bids_app", "run_local_script", "run_tractography", "build_structural_connectome"}


def _toolspec_index() -> dict[str, ToolSpec]:
    loaded = load_tool_specs(force_reload=True, exposed_only=False)
    if isinstance(loaded, dict):
        specs = loaded.values()
    else:
        specs = loaded
    return {
        str(spec.name).strip(): spec
        for spec in specs
        if isinstance(getattr(spec, "name", None), str) and str(spec.name).strip()
    }


def _workflow_catalog_entries() -> list[dict[str, Any]]:
    path = Path("configs/workflows/workflow_catalog.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [row for row in data.get("workflows") or [] if isinstance(row, dict)]


def _workflow_step_names(entry: dict[str, Any]) -> list[str]:
    runtime = entry.get("runtime") if isinstance(entry, dict) else None
    steps = runtime.get("steps") if isinstance(runtime, dict) else None
    names: list[str] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        name = str(step.get("tool") or "").strip()
        if name:
            names.append(name)
    return names


def _workflow_external_runtime_steps(
    step_names: list[str], specs: dict[str, ToolSpec]
) -> list[str]:
    external: list[str] = []
    for step_name in step_names:
        lowered = step_name.lower()
        if lowered in _EXTERNAL_STEPS or any(
            lowered.startswith(prefix) for prefix in _EXTERNAL_STEP_PREFIXES
        ):
            external.append(step_name)
            continue
        spec = specs.get(step_name)
        if spec is None:
            continue
        runtime = infer_requires_runtime(spec.requires_runtime, backend=spec.backend)
        if runtime == "container" or str(spec.backend or "").strip().lower() == "niwrap":
            external.append(step_name)
    return sorted(set(external))


def _tool_flags(metadata: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    kind = metadata.get("execution_story_kind")
    hosted_flag = bool(metadata.get("hosted_via_br_mcp_service"))
    targets = list(metadata.get("supported_recipe_targets") or [])
    declared_targets = metadata.get("declared_supported_recipe_targets")
    declared_primary_target = str(metadata.get("declared_primary_target") or "").strip()
    has_declared = bool(metadata.get("has_declared_recipe_metadata"))
    if not has_declared:
        flags.append("missing_declaration")
    if not kind:
        flags.append("missing_story")
    if kind == "hosted_or_stateful_service" and targets:
        flags.append("hosted_advertises_runnable_target")
    if kind == "hosted_or_stateful_service" and not hosted_flag:
        flags.append("hosted_missing_service_flag")
    if kind != "hosted_or_stateful_service" and hosted_flag:
        flags.append("non_hosted_sets_service_flag")
    if kind == "portable_python_compute" and "python" not in targets:
        flags.append("portable_python_missing_python_target")
    if (
        isinstance(declared_targets, list)
        and declared_targets
        and declared_primary_target
        and declared_primary_target not in declared_targets
    ):
        flags.append("declared_primary_target_invalid")
    return flags


def _workflow_flags(
    *,
    metadata: dict[str, Any],
    surfaced: bool,
    external_runtime_steps: list[str],
) -> list[str]:
    flags = _tool_flags(metadata)
    targets = list(metadata.get("supported_recipe_targets") or [])
    inferred_targets = list(metadata.get("inferred_supported_recipe_targets") or [])
    if external_runtime_steps and "python" in targets and "python" not in inferred_targets:
        flags.append("workflow_external_runtime_advertises_python")
    if not surfaced:
        flags.append("workflow_catalog_not_surfaced")
    return sorted(set(flags))


def build_audit() -> dict[str, Any]:
    tool_specs_loaded = load_tool_specs(force_reload=True, exposed_only=True)
    if isinstance(tool_specs_loaded, dict):
        exposed_tool_specs = list(tool_specs_loaded.values())
    else:
        exposed_tool_specs = list(tool_specs_loaded)
    all_specs = _toolspec_index()
    workflow_catalog = _workflow_catalog_entries()
    workflow_catalog_by_id = {
        str(row.get("id") or "").strip(): row
        for row in workflow_catalog
        if str(row.get("id") or "").strip()
    }
    workflow_surface_rows = mcp_server.workflow_search("", limit=500).get("workflows", [])
    workflow_surface_by_id = {
        str(row.get("id") or "").strip(): row
        for row in workflow_surface_rows
        if str(row.get("id") or "").strip()
    }
    orchestration_ids = sorted(load_orchestration_workflows())

    tool_rows: list[dict[str, Any]] = []
    for spec in exposed_tool_specs:
        metadata = resolve_recipe_metadata(spec.name, spec=spec)
        tool_rows.append(
            {
                "subject_type": "tool",
                "id": spec.name,
                "requires_runtime": infer_requires_runtime(
                    spec.requires_runtime, backend=spec.backend
                ),
                "backend": spec.backend,
                "has_declared_recipe_metadata": metadata[
                    "has_declared_recipe_metadata"
                ],
                "declared_execution_story_kind": metadata[
                    "declared_execution_story_kind"
                ],
                "declared_supported_recipe_targets": metadata[
                    "declared_supported_recipe_targets"
                ],
                "declared_primary_target": metadata["declared_primary_target"],
                "declared_recipe_sources": metadata["declared_recipe_sources"],
                "inferred_execution_story_kind": metadata[
                    "inferred_execution_story_kind"
                ],
                "inferred_supported_recipe_targets": metadata[
                    "inferred_supported_recipe_targets"
                ],
                "inferred_primary_target": metadata["inferred_primary_target"],
                "execution_story_kind": metadata["execution_story_kind"],
                "hosted_via_br_mcp_service": metadata[
                    "hosted_via_br_mcp_service"
                ],
                "supported_recipe_targets": metadata["supported_recipe_targets"],
                "recipe_depth": metadata["recipe_depth"],
                "primary_target": metadata["primary_target"],
                "flags": _tool_flags(metadata),
            }
        )

    workflow_rows: list[dict[str, Any]] = []
    for workflow_id, entry in sorted(workflow_catalog_by_id.items()):
        metadata = resolve_recipe_metadata(workflow_id, workflow_entry=entry)
        step_names = _workflow_step_names(entry)
        external_steps = _workflow_external_runtime_steps(step_names, all_specs)
        surfaced_row = workflow_surface_by_id.get(workflow_id)
        workflow_rows.append(
            {
                "subject_type": "workflow",
                "id": workflow_id,
                "cost_tier": str(entry.get("cost_tier") or "").strip().lower() or None,
                "orchestration_allowlisted": workflow_id in orchestration_ids,
                "surfaced_by_workflow_search": bool(surfaced_row),
                "requires_runtime": surfaced_row.get("requires_runtime")
                if isinstance(surfaced_row, dict)
                else None,
                "step_tools": step_names,
                "external_runtime_steps": external_steps,
                "has_declared_recipe_metadata": metadata[
                    "has_declared_recipe_metadata"
                ],
                "declared_execution_story_kind": metadata[
                    "declared_execution_story_kind"
                ],
                "declared_supported_recipe_targets": metadata[
                    "declared_supported_recipe_targets"
                ],
                "declared_primary_target": metadata["declared_primary_target"],
                "declared_recipe_sources": metadata["declared_recipe_sources"],
                "inferred_execution_story_kind": metadata[
                    "inferred_execution_story_kind"
                ],
                "inferred_supported_recipe_targets": metadata[
                    "inferred_supported_recipe_targets"
                ],
                "inferred_primary_target": metadata["inferred_primary_target"],
                "execution_story_kind": metadata["execution_story_kind"],
                "hosted_via_br_mcp_service": metadata[
                    "hosted_via_br_mcp_service"
                ],
                "supported_recipe_targets": metadata["supported_recipe_targets"],
                "recipe_depth": metadata["recipe_depth"],
                "primary_target": metadata["primary_target"],
                "flags": _workflow_flags(
                    metadata=metadata,
                    surfaced=bool(surfaced_row),
                    external_runtime_steps=external_steps,
                ),
            }
        )

    all_flags = Counter(
        flag for row in [*tool_rows, *workflow_rows] for flag in row.get("flags") or []
    )
    story_kind_mismatches = [
        row["id"]
        for row in [*tool_rows, *workflow_rows]
        if row.get("declared_execution_story_kind")
        and row.get("inferred_execution_story_kind")
        and row["declared_execution_story_kind"] != row["inferred_execution_story_kind"]
    ]
    target_mismatches = [
        row["id"]
        for row in [*tool_rows, *workflow_rows]
        if isinstance(row.get("declared_supported_recipe_targets"), list)
        and row.get("declared_supported_recipe_targets")
        != row.get("inferred_supported_recipe_targets")
    ]
    primary_target_mismatches = [
        row["id"]
        for row in [*tool_rows, *workflow_rows]
        if str(row.get("declared_primary_target") or "").strip()
        and str(row.get("declared_primary_target") or "").strip()
        != str(row.get("inferred_primary_target") or "").strip()
    ]
    return {
        "summary": {
            "exposed_tools": len(tool_rows),
            "workflow_catalog_entries": len(workflow_rows),
            "workflow_search_surface_entries": len(workflow_surface_rows),
            "workflow_catalog_missing_from_surface": sorted(
                set(workflow_catalog_by_id) - set(workflow_surface_by_id)
            ),
            "tool_story_kinds": dict(
                Counter(row["execution_story_kind"] for row in tool_rows)
            ),
            "workflow_story_kinds": dict(
                Counter(row["execution_story_kind"] for row in workflow_rows)
            ),
            "declared_story_kind_mismatches": sorted(story_kind_mismatches),
            "declared_supported_target_mismatches": sorted(target_mismatches),
            "declared_primary_target_mismatches": sorted(primary_target_mismatches),
            "flag_counts": dict(all_flags),
        },
        "tools": tool_rows,
        "workflows": workflow_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the JSON audit report.",
    )
    parser.add_argument(
        "--fail-on-flags",
        action="store_true",
        help="Exit non-zero when the audit report contains any flagged tools/workflows.",
    )
    args = parser.parse_args()

    payload = build_audit()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is None:
        print(text)
    else:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(args.output)
    if args.fail_on_flags and payload["summary"].get("flag_counts"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
