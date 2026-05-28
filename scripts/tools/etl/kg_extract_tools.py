"""
Extract tool / intent / synonym data from the agent catalog for KG ingestion.

This module only produces Python dictionaries. Writing to Neo4j is handled
by kg_ingest_tools.py.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import yaml

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.agent.planner.catalog_loader import (
    get_capability_index,
    load_intents,
)
from brain_researcher.services.agent.planner.synonyms_loader import (
    _load_intent_synonym_map,
)
from brain_researcher.services.mcp.execution_recipes import recipe_card_metadata

# -----------------------------
# Helpers
# -----------------------------


def _infer_family_id(package: str) -> str:
    pkg = (package or "").lower()
    if pkg.startswith("fsl"):
        return "fsl"
    if pkg.startswith("afni"):
        return "afni"
    if pkg.startswith("mrtrix"):
        return "mrtrix3"
    if pkg.startswith("workbench"):
        return "workbench"
    if pkg.startswith("ants"):
        return "ants"
    if pkg.startswith("freesurfer"):
        return "freesurfer"
    if pkg.startswith("bidsapp"):
        return "bidsapps"
    if pkg.startswith("qsiprep"):
        return "bidsapps"
    if pkg.startswith("mriqc"):
        return "bidsapps"
    if pkg.startswith("fmriprep"):
        return "bidsapps"
    return "niwrap_generic"


@lru_cache(maxsize=1)
def _load_promoted_niwrap() -> list[dict[str, str]]:
    """Load promoted NiWrap whitelist from configs/kg_promoted_niwrap.yaml."""
    path = resolve_from_config("kg_promoted_niwrap.yaml")
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return data.get("promoted", []) or []
    except Exception:
        return []


def _is_promoted_niwrap(cap, promoted_specs: list[dict[str, str]]) -> bool:
    """Check if a capability matches promoted NiWrap list."""
    if not getattr(cap, "entrypoint", None):
        return False
    pkg = (cap.package or "").lower()
    ep = (cap.entrypoint or "").lower()
    for spec in promoted_specs:
        spkg = (spec.get("package") or "").lower()
        sep = (spec.get("entrypoint") or "").lower()
        sid = (spec.get("id") or "").lower()
        if sid and cap.id.lower() == sid:
            return True
        if spkg and sep and pkg == spkg and ep == sep:
            return True
        if spkg and not sep and pkg == spkg:
            return True
    return False


def _dedupe_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


@lru_cache(maxsize=1)
def _load_workflow_catalog() -> list[dict[str, Any]]:
    path = resolve_from_config("workflows", "workflow_catalog.yaml")
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return []
    workflows = data.get("workflows") if isinstance(data, dict) else None
    return [row for row in workflows or [] if isinstance(row, dict)]


@lru_cache(maxsize=1)
def _workflow_entrypoint_family_ids() -> dict[str, list[str]]:
    path = resolve_from_config("catalog", "tool_family_cards.yaml")
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}

    mapping: dict[str, list[str]] = {}
    for card in data.get("family_cards", []) or []:
        if not isinstance(card, dict):
            continue
        family_ids = _dedupe_texts(card.get("graph_family_ids") or [])
        if not family_ids:
            continue
        for entrypoint in card.get("canonical_entrypoints", []) or []:
            entrypoint_text = str(entrypoint or "").strip()
            if not entrypoint_text:
                continue
            existing = mapping.setdefault(entrypoint_text, [])
            for family_id in family_ids:
                if family_id not in existing:
                    existing.append(family_id)
    return mapping


def _workflow_step_tools(workflow: dict[str, Any]) -> list[str]:
    runtime = (
        workflow.get("runtime") if isinstance(workflow.get("runtime"), dict) else {}
    )
    steps = runtime.get("steps") if isinstance(runtime.get("steps"), list) else []
    return _dedupe_texts(
        [
            step.get("tool")
            for step in steps
            if isinstance(step, dict) and step.get("tool") is not None
        ]
    )


def _workflow_required_inputs(workflow: dict[str, Any]) -> list[str]:
    params = workflow.get("params") if isinstance(workflow.get("params"), dict) else {}
    schema = params.get("schema") if isinstance(params.get("schema"), dict) else {}
    required = (
        schema.get("required") if isinstance(schema.get("required"), list) else []
    )
    return _dedupe_texts(required)


def _workflow_declared_outputs(workflow: dict[str, Any]) -> list[str]:
    artifact_contract = (
        workflow.get("artifact_contract")
        if isinstance(workflow.get("artifact_contract"), dict)
        else {}
    )
    values: list[Any] = []
    for key in (
        "required_outputs",
        "optional_outputs",
        "report_files",
        "provenance_files",
    ):
        rows = artifact_contract.get(key)
        if isinstance(rows, list):
            values.extend(rows)
    return _dedupe_texts(values)


def _workflow_family_fallback(workflow_id: str, workflow: dict[str, Any]) -> list[str]:
    explicit = {
        "workflow_fmriprep_preprocessing": ["bidsapps"],
        "workflow_mriqc": ["bidsapps"],
        "workflow_qsiprep": ["bidsapps"],
        "workflow_qsirecon": ["mrtrix3"],
        "workflow_dwi_connectome": ["mrtrix3"],
        "workflow_fastsurfer": ["freesurfer"],
        "workflow_task_glm_group": ["fsl"],
        "workflow_fitlins_direct": ["bidsapps"],
        "workflow_fitlins_multiverse_yeo17": ["bidsapps"],
        "workflow_group_ica": ["fsl"],
        "workflow_longitudinal_lme": ["niwrap_generic"],
        "workflow_subtype_discovery": ["niwrap_generic"],
        "workflow_precision_parcellation": ["workbench"],
    }
    if workflow_id in explicit:
        return explicit[workflow_id]

    recipe_family = str(workflow.get("recipe_family") or "").strip().lower()
    recipe_family_map = {
        "bids_app_preprocessing": ["bidsapps"],
        "bids_app_qc": ["bidsapps"],
        "dwi_preprocessing": ["bidsapps"],
        "dwi_connectome": ["mrtrix3"],
        "dwi_reconstruction": ["mrtrix3"],
        "structural_reconstruction": ["freesurfer"],
        "task_glm_group": ["fsl"],
        "fitlins_direct": ["bidsapps"],
        "fitlins_multiverse": ["bidsapps"],
        "group_ica": ["fsl"],
        "longitudinal_lme": ["niwrap_generic"],
        "subtype_discovery": ["niwrap_generic"],
        "precision_parcellation": ["workbench"],
    }
    if recipe_family in recipe_family_map:
        return recipe_family_map[recipe_family]

    modalities = {
        str(value or "").strip().lower()
        for value in (workflow.get("modalities") or [])
        if str(value or "").strip()
    }
    if "dmri" in modalities:
        return ["mrtrix3"]
    if "smri" in modalities:
        return ["freesurfer"]
    if "fmri" in modalities:
        return ["fsl"]
    return ["niwrap_generic"]


def _workflow_family_ids(workflow_id: str, workflow: dict[str, Any]) -> list[str]:
    card_families = _workflow_entrypoint_family_ids().get(workflow_id) or []
    if card_families:
        return card_families
    return _workflow_family_fallback(workflow_id, workflow)


def _flatten_recipe_metadata(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_recipe_available": bool(card.get("execution_recipe_available")),
        "execution_story_kind": card.get("execution_story_kind"),
        "execution_story": (
            card.get("execution_story", {}).get("summary")
            if isinstance(card.get("execution_story"), dict)
            else card.get("execution_story")
        ),
        "supported_recipe_targets": _dedupe_texts(
            card.get("supported_recipe_targets") or []
        ),
        "primary_target": card.get("primary_target"),
        "canonical_tool_id": card.get("canonical_tool_id"),
        "recipe_depth": card.get("recipe_depth"),
        "hosted_via_br_mcp_service": bool(card.get("hosted_via_br_mcp_service")),
        "recipe_first_workflow": bool(card.get("recipe_first_workflow")),
        "heavy_runtime_workflow": bool(card.get("heavy_runtime_workflow")),
        "batch_analysis_workflow": bool(card.get("batch_analysis_workflow")),
        "workflow_surface_class": card.get("workflow_surface_class"),
        "mcp_execution_posture": card.get("mcp_execution_posture"),
        "direct_tool_execution_supported": card.get("direct_tool_execution_supported"),
        "manual_pipeline_execution_only": card.get("manual_pipeline_execution_only"),
        "recommended_mcp_entrypoint": card.get("recommended_mcp_entrypoint"),
        "execution_guidance": card.get("execution_guidance"),
        "neurodesk_package_name": card.get("neurodesk_package_name"),
        "neurodesk_module_name": card.get("neurodesk_module_name"),
        "neurodesk_recommended_version": card.get("neurodesk_recommended_version"),
        "neurodesk_recommended_module": card.get("neurodesk_recommended_module"),
    }


def _workflow_tool_row(workflow: dict[str, Any]) -> dict[str, Any] | None:
    workflow_id = str(workflow.get("id") or "").strip()
    if not workflow_id:
        return None

    recipe_meta = _flatten_recipe_metadata(
        recipe_card_metadata(workflow_id, workflow_entry=workflow)
    )
    family_ids = _workflow_family_ids(workflow_id, workflow)
    modalities = _dedupe_texts(workflow.get("modalities") or [])
    artifact_contract = (
        workflow.get("artifact_contract")
        if isinstance(workflow.get("artifact_contract"), dict)
        else {}
    )
    example_dataset = (
        workflow.get("example_dataset")
        if isinstance(workflow.get("example_dataset"), dict)
        else {}
    )
    reference_assets = _dedupe_texts(workflow.get("reference_assets") or [])
    backend_options = (
        workflow.get("backend_options")
        if isinstance(workflow.get("backend_options"), dict)
        else {}
    )

    return {
        "id": workflow_id,
        "name": workflow_id,
        "package": str(workflow.get("recipe_family") or "workflow").strip()
        or "workflow",
        "runtime_kind": "workflow",
        "entrypoint": str(workflow.get("impl") or "").strip() or None,
        "modality": modalities,
        "intents": [],
        "family_id": family_ids[0],
        "family_ids": family_ids,
        "is_niwrap": False,
        "is_promoted": False,
        "is_curated": True,
        "source": "workflow_catalog/vFinal",
        "description": str(
            workflow.get("description") or workflow.get("impl") or workflow_id
        ).strip(),
        "capabilities": _workflow_step_tools(workflow),
        "consumes": _workflow_required_inputs(workflow),
        "produces": _workflow_declared_outputs(workflow),
        "cpu_min": 1,
        "mem_mb_min": 512,
        "gpu": False,
        "time_min_default": 60.0
        if str(workflow.get("cost_tier") or "").strip().lower() == "expensive"
        else 5.0,
        "stage": workflow.get("stage"),
        "cost_tier": workflow.get("cost_tier"),
        "origin": workflow.get("origin"),
        "lifecycle": workflow.get("lifecycle"),
        "recipe_family": workflow.get("recipe_family"),
        "stable_workflow_pack": bool(workflow.get("stable_workflow_pack")),
        "source_repo": workflow.get("source_repo"),
        "source_paper": workflow.get("source_paper"),
        "tested_release": workflow.get("tested_release"),
        "reference_assets": reference_assets,
        "backend_options_available": _dedupe_texts(
            backend_options.get("available") or []
        ),
        "backend_default": backend_options.get("default"),
        "example_dataset_id": example_dataset.get("dataset_id"),
        "runbook": workflow.get("runbook"),
        "artifact_required_outputs": _dedupe_texts(
            artifact_contract.get("required_outputs") or []
        ),
        "artifact_optional_outputs": _dedupe_texts(
            artifact_contract.get("optional_outputs") or []
        ),
        "artifact_report_files": _dedupe_texts(
            artifact_contract.get("report_files") or []
        ),
        **recipe_meta,
    }


# -----------------------------
# Extraction functions
# -----------------------------


def extract_operations() -> tuple[list[dict], list[tuple[str, str]]]:
    intents = load_intents()
    ops = []
    children = []
    for intent in intents.values():
        ops.append(
            {
                "id": intent.id,
                "name": intent.name,
                "description": intent.description,
                "domains": intent.domains,
                "modalities": intent.modalities,
                "analysis_level": intent.analysis_level,
                "parents": intent.parents,
            }
        )
        for p in intent.parents or []:
            children.append((p, intent.id))
    return ops, children


def extract_synonyms() -> list[dict]:
    syn_map = _load_intent_synonym_map()
    rows = []
    for intent_id, words in syn_map.items():
        for text in words:
            rows.append(
                {
                    "operation_id": intent_id,
                    "text": text.lower(),
                    "lang": "en",
                    "kind": "natural_language",
                    "source": "intent_synonyms.yaml",
                }
            )
    return rows


def extract_tools_and_families() -> tuple[list[dict], list[dict]]:
    idx = get_capability_index()
    families: dict[str, dict] = {}
    tools: list[dict] = []
    promoted = _load_promoted_niwrap()

    limit_env = os.environ.get("BR_NIWRAP_LIMIT")
    limit = int(limit_env) if limit_env else None

    count = 0
    for cap in idx.by_id.values():
        # Optional cap to keep CI light
        if limit and cap.id.startswith("container.") and count >= limit:
            continue

        fam_id = _infer_family_id(cap.package)
        fam = families.setdefault(
            fam_id,
            {
                "id": fam_id,
                "name": fam_id.upper(),
                "runtime_kinds": set(),
                "packages": set(),
                "source": "catalog_capabilities/v1",
            },
        )
        fam["runtime_kinds"].add(cap.runtime_kind)
        fam["packages"].add(cap.package)

        # Extract resource requirements
        resources = getattr(cap, "resources", None)
        cpu_min = getattr(resources, "cpu_min", 1) if resources else 1
        mem_mb_min = getattr(resources, "mem_mb_min", 512) if resources else 512
        gpu = getattr(resources, "gpu", False) if resources else False
        time_min_default = (
            getattr(resources, "time_min_default", 5.0) if resources else 5.0
        )

        tools.append(
            {
                "id": cap.id,
                "name": cap.name,
                "package": cap.package,
                "runtime_kind": cap.runtime_kind,
                "entrypoint": getattr(cap, "entrypoint", None),
                "modality": cap.modality,
                "intents": cap.intents,
                "family_id": fam_id,
                "family_ids": [fam_id],
                "is_niwrap": getattr(cap, "metadata", None)
                and getattr(cap.metadata, "source", "") == "niwrap_auto",
                "is_promoted": _is_promoted_niwrap(cap, promoted),
                "is_curated": getattr(cap, "source", "") == "catalog",
                "source": getattr(cap, "source", "catalog_capabilities/v1"),
                # New fields for KG retrieval
                "description": getattr(cap, "description", None),
                "capabilities": getattr(cap, "capabilities", []),
                "consumes": getattr(cap, "consumes", []),
                "produces": getattr(cap, "produces", []),
                "cpu_min": cpu_min,
                "mem_mb_min": mem_mb_min,
                "gpu": gpu,
                "time_min_default": time_min_default,
            }
        )
        count += 1

    for workflow in _load_workflow_catalog():
        tool_row = _workflow_tool_row(workflow)
        if not tool_row:
            continue
        for family_id in tool_row["family_ids"]:
            fam = families.setdefault(
                family_id,
                {
                    "id": family_id,
                    "name": family_id.upper(),
                    "runtime_kinds": set(),
                    "packages": set(),
                    "source": "catalog_capabilities/v1",
                },
            )
            fam["runtime_kinds"].add(tool_row["runtime_kind"])
            fam["packages"].add(tool_row["package"])
        tools.append(tool_row)

    # finalize families
    for fam in families.values():
        fam["runtime_kinds"] = sorted(fam["runtime_kinds"])
        fam["packages"] = sorted(fam["packages"])

    return list(families.values()), tools


def aggregate_family_ops(tools: list[dict]) -> list[dict]:
    agg: dict[tuple, int] = {}
    for t in tools:
        for intent in t.get("intents", []):
            key = (t["family_id"], intent)
            agg[key] = agg.get(key, 0) + 1
    rows = []
    for (fam, op), n in agg.items():
        rows.append({"family_id": fam, "operation_id": op, "tool_count": n})
    return rows


if __name__ == "__main__":
    ops, children = extract_operations()
    syns = extract_synonyms()
    fams, tools = extract_tools_and_families()
    fam_ops = aggregate_family_ops(tools)
    print(
        f"ops={len(ops)}, syns={len(syns)}, families={len(fams)}, tools={len(tools)}, fam_ops={len(fam_ops)}"
    )
