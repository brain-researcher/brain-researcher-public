"""Stateless execution recipe generation for public MCP tools."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from functools import lru_cache
from pathlib import Path
from textwrap import dedent
from typing import Any

from brain_researcher.services.mcp.slurm_tools import (
    DEFAULT_PROFILE as SHERLOCK_DEFAULT_PROFILE,
)
from brain_researcher.services.mcp.slurm_tools import (
    sherlock_render_sbatch_script,
)
from brain_researcher.services.shared.planner.handoff import (
    build_handoff_from_recipe_context,
)
from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)
from brain_researcher.services.tools.runtime_profiles import (
    execution_recipe_config_path,
    get_container_image,
    get_neurodesk_package_profile,
    get_tool_recipe_declaration,
    get_tool_recipe_override,
    normalize_runtime_package_name,
)
from brain_researcher.services.tools.spec import (
    ToolExecutionCapabilities,
    ToolSpec,
    infer_requires_runtime,
)

RECIPE_TARGETS = ("python", "neurodesk", "container", "slurm")
AUTO_RECIPE_TARGETS = ("auto", "default", "")
DEFAULT_CLUSTER_PROFILE = "generic"
EXECUTION_STORY_KINDS = (
    "portable_python_compute",
    "binary_backed_atomic",
    "hosted_or_stateful_service",
    "composite_workflow",
)
_BIDS_APPS = {"fmriprep", "mriqc", "qsiprep", "fitlins"}
_HEAVY_WORKFLOW_STEPS = {
    "run_bids_app",
    "run_tractography",
    "build_structural_connectome",
}
_DIRECT_PYTHON_WORKFLOWS = {"workflow_rest_connectome_e2e"}
_FIRST_WAVE_HEAVY_RUNTIME_WORKFLOWS = frozenset(
    {
        "workflow_fmriprep_preprocessing",
        "workflow_mriqc",
        "workflow_qsiprep",
        "workflow_dwi_connectome",
        "workflow_qsirecon",
        "workflow_fastsurfer",
    }
)
_LONG_RUNNING_BATCH_ANALYSIS_WORKFLOWS = frozenset(
    {
        "workflow_group_ica",
        "workflow_task_glm_group",
        "workflow_fitlins_direct",
        "workflow_fitlins_multiverse_yeo17",
        "workflow_longitudinal_lme",
        "workflow_subtype_discovery",
        "workflow_precision_parcellation",
    }
)
_NEURODESK_PREFIX_MAP = {
    "fsl.": "fsl",
    "fsl_": "fsl",
    "afni.": "afni",
    "afni_": "afni",
    "ants.": "ants",
    "ants_": "ants",
    "freesurfer.": "freesurfer",
    "freesurfer_": "freesurfer",
    "mrtrix3.": "mrtrix3",
    "mrtrix3_": "mrtrix3",
    "spm12.": "cat12",
    "spm12_": "cat12",
}
_RECIPE_TOOL_ALIASES = {
    "fsl bet": "fsl_bet",
    "fsl bet run": "fsl_bet",
}
_NON_PORTABLE_STEP_PREFIXES = (
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
_HOSTED_TOOL_IDS = {
    "concept_literature_search",
    "datasets.client",
    "datasets.describe_resources",
    "datasets.list_resources",
    "evidence_pack",
    "find_related_concepts",
    "graph_query",
    "kg_multihop_qa",
    "literature_mining",
    "neurokg.client",
    "neurokg.detect_contradiction_motifs",
    "neurokg.detect_topology_shifts",
    "neurokg.find_structural_leverage",
    "neurokg.sample_ood_hypothesis",
    "pipeline.search",
    "query_neuromaps",
}
_DIRECT_PYTHON_RECIPE_FAMILIES = {
    "connectivity_matrix",
    "encoding_models",
    "glm",
    "mvpa",
    "searchlight",
    "seed_based_connectivity",
    "temporal_decoding",
}
_WORKFLOW_INFERENCE_OVERRIDES = {
    # These workflows intentionally expose a curated recipe surface that differs
    # from the naive step-runtime heuristic, typically because they are
    # wrapper-backed or rely on internal alias steps.
    "workflow_rest_connectome_e2e": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_seed_based_connectivity": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_network_based_statistics": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_connectivity_gradients": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_group_ica": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_data_harmonization": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_literature_search_synthesis": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_neurometabench_official_adapter": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_neurosynth_roi_analysis": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_spatial_correlation": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_task_glm_group": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_fitlins_direct": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_fitlins_multiverse_yeo17": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_longitudinal_lme": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_subtype_discovery": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_precision_parcellation": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_hypothesis_candidate_cards": {
        "execution_story_kind": "portable_python_compute",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_realtime_twophoton_closed_loop": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_fmriprep_preprocessing": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_mriqc": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_qsiprep": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_preprocessing_qc": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_asl_perfusion": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "qbold_fabber": {
        "execution_story_kind": "binary_backed_atomic",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "calibrated_perfusion_surrogate": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["python"],
        "primary_target": "python",
    },
    "workflow_dwi_connectome": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_ppi_analysis": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_sc_fc_coupling": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_vbm_analysis": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
    },
    "workflow_smriprep": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["container", "slurm"],
        "primary_target": "container",
    },
    "workflow_qsirecon": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["container", "slurm"],
        "primary_target": "container",
    },
    "workflow_fastsurfer": {
        "execution_story_kind": "composite_workflow",
        "supported_recipe_targets": ["container"],
        "primary_target": "container",
    },
}


def _resolve_neurodesk_package_profile(tool_id: str) -> dict[str, Any] | None:
    lookup_tool_id = _recipe_lookup_tool_id(tool_id)
    canonical_tool_id = (
        resolve_primary_runtime_tool_id(lookup_tool_id) or lookup_tool_id
    )
    lowered = str(canonical_tool_id or "").strip().lower()
    if not lowered:
        return None

    direct_profile = get_neurodesk_package_profile(lowered)
    if isinstance(direct_profile, dict):
        return direct_profile

    normalized_package = normalize_runtime_package_name(lowered)
    if normalized_package and normalized_package != lowered:
        alias_profile = get_neurodesk_package_profile(normalized_package)
        if isinstance(alias_profile, dict):
            return alias_profile

    for prefix, package in _NEURODESK_PREFIX_MAP.items():
        if lowered.startswith(prefix):
            profile = get_neurodesk_package_profile(package)
            if isinstance(profile, dict):
                return profile
    return None


def _recipe_lookup_tool_id(tool_id: str) -> str:
    requested = str(tool_id or "").strip()
    if not requested:
        return ""
    alias_key = re.sub(r"[^a-z0-9]+", " ", requested.lower()).strip()
    return _RECIPE_TOOL_ALIASES.get(alias_key, requested)


def _neurodesk_module_resolution(tool_id: str) -> dict[str, Any]:
    profile = _resolve_neurodesk_package_profile(tool_id)
    if not isinstance(profile, dict):
        return {}

    package_name = str(profile.get("name") or "").strip().lower()
    module_name = str(profile.get("module_name") or package_name).strip()
    recommended_version = str(
        profile.get("recommended_version") or profile.get("version") or ""
    ).strip()
    available_versions = _normalize_list(profile.get("available_versions"))
    if recommended_version and recommended_version not in available_versions:
        available_versions.insert(0, recommended_version)

    available_modules = [
        f"{module_name}/{version}" for version in available_versions if version
    ]
    if not available_modules and recommended_version:
        available_modules = [f"{module_name}/{recommended_version}"]
    if not available_modules and module_name:
        available_modules = [module_name]

    recommended_module = (
        f"{module_name}/{recommended_version}"
        if module_name and recommended_version
        else (available_modules[0] if available_modules else "")
    )

    return {
        "neurodesk_package_name": package_name or module_name.lower(),
        "neurodesk_module_name": module_name,
        "neurodesk_recommended_version": recommended_version,
        "neurodesk_available_versions": available_versions,
        "neurodesk_recommended_module": recommended_module,
        "neurodesk_available_modules": available_modules,
    }


def _hosted_via_br_mcp_service(execution_story_kind: str) -> bool:
    return str(execution_story_kind or "").strip() == "hosted_or_stateful_service"


def normalize_recipe_target(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        values.append(text)
        seen.add(text)
    return values


def _normalize_dict(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _merge_workflow_default_params(
    params: dict[str, Any], workflow_entry: dict[str, Any] | None
) -> dict[str, Any]:
    if not isinstance(workflow_entry, dict):
        return dict(params)
    workflow_id = str(workflow_entry.get("id") or "").strip()
    if workflow_id not in {
        "workflow_fitlins_direct",
        "workflow_fitlins_multiverse_yeo17",
    }:
        return dict(params)
    params_block = _normalize_dict(workflow_entry.get("params"))
    defaults = _normalize_dict(params_block.get("defaults"))
    if not defaults:
        return dict(params)
    merged = dict(defaults)
    merged.update(params)
    return merged


def _workflow_inference_override(
    tool_id: str, workflow_entry: dict[str, Any] | None
) -> dict[str, Any]:
    if not isinstance(workflow_entry, dict):
        return {}
    workflow_id = str(workflow_entry.get("id") or tool_id or "").strip()
    override = _WORKFLOW_INFERENCE_OVERRIDES.get(workflow_id) or {}
    if not isinstance(override, dict):
        return {}
    supported_targets = None
    if "supported_recipe_targets" in override:
        supported_targets = _normalize_list(override.get("supported_recipe_targets"))
    primary_target = None
    if "primary_target" in override:
        primary_target = normalize_recipe_target(override.get("primary_target"))
    return {
        "execution_story_kind": _declared_story_kind(
            override.get("execution_story_kind")
        ),
        "supported_recipe_targets": supported_targets,
        "primary_target": primary_target,
    }


def _slugify(tool_id: str) -> str:
    return (
        re.sub(r"[^a-zA-Z0-9]+", "_", str(tool_id or "").strip()).strip("_") or "tool"
    )


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


_PACK_CONTRACT_SCHEMA_VERSION = "br-pack-contract-v1"
_PACK_RUNTIME_MANIFEST_SCHEMA_VERSION = "br-pack-runtime-manifest-v1"
_PACK_MANIFEST_FILE = "pack_manifest.json"
_PACK_RUNNER_FILE = "run_pack.py"
_PACK_PRECHECK_INPUT_HINTS = {
    "img": "nifti_image",
    "atlas": "nifti_image",
    "atlas_path": "nifti_image",
    "mask_img": "nifti_image",
    "func_file": "nifti_image",
    "fmri_path": "nifti_image",
    "volume_img": "nifti_image",
    "stat_map": "nifti_image",
    "contrast_map": "nifti_image",
    "contrast_maps": "nifti_list",
    "confounds": "table",
    "confounds_file": "table",
    "timeseries": "array_or_table",
    "brain_data_file": "array_or_table",
    "stimulus_file": "array_or_table",
}


def _stable_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _maybe_tool_schema_hash(
    tool_id: str,
    *,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
) -> str | None:
    if spec is not None:
        json_schema = _normalize_dict(spec.json_schema)
        payload = {
            "tool_id": tool_id,
            "json_schema": json_schema,
            "required": _normalize_list(json_schema.get("required"))
            or list(spec.required),
        }
        return _stable_json_hash(payload)
    if isinstance(workflow_entry, dict):
        params = _normalize_dict(workflow_entry.get("params"))
        schema = _normalize_dict(params.get("schema"))
        if schema:
            payload = {
                "tool_id": tool_id,
                "json_schema": schema,
                "required": _normalize_list(schema.get("required")),
            }
            return _stable_json_hash(payload)
    return None


def _pack_input_bindings(params: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for param_name, kind in _PACK_PRECHECK_INPUT_HINTS.items():
        if param_name not in params:
            continue
        key = (param_name, kind)
        if key in seen:
            continue
        seen.add(key)
        bindings.append({"param": param_name, "kind": kind})
    return bindings


def _declared_output_bindings(
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    output_file = str(params.get("output_file") or "").strip()
    if output_file:
        key = ("param_path", "output_file", "")
        seen.add(key)
        bindings.append({"kind": "param_path", "param": "output_file"})

    output_dir = str(params.get("output_dir") or "").strip()
    artifact_contract = (
        metadata.get("artifact_contract")
        if isinstance(metadata.get("artifact_contract"), dict)
        else {}
    )
    required_outputs = _normalize_list(artifact_contract.get("required_outputs"))
    if output_dir and required_outputs:
        for relpath in required_outputs:
            key = ("output_dir_artifact", "output_dir", relpath)
            if key in seen:
                continue
            seen.add(key)
            bindings.append(
                {
                    "kind": "output_dir_artifact",
                    "param": "output_dir",
                    "relative_path": relpath,
                }
            )
    return bindings


def _pack_confounds_policy(tool_id: str) -> str | None:
    if str(tool_id or "").strip() == "clean_confounds":
        return "sanitize_non_finite_to_zero"
    return None


def _base_python_pack_manifest(
    *,
    tool_id: str,
    metadata: dict[str, Any],
    required_env_vars: list[str],
    step: dict[str, Any],
    params: dict[str, Any],
    handoff: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": _PACK_CONTRACT_SCHEMA_VERSION,
        "pack_id": f"{_slugify(tool_id)}_python_pack",
        "tool_id": tool_id,
        "target_runtime": "python",
        "generator": {
            "kind": "execution_recipe",
            "config_path": metadata.get("config_path"),
        },
        "required_env_vars": required_env_vars,
        "resource_profile": _normalize_dict(metadata.get("resource_profile")),
        "resume_policy": "skip_if_log_success_and_outputs_exist",
        "preflight": {
            "blocking_levels": ["L1", "L2"],
            "advisory_levels": ["L3"],
            "inputs": _pack_input_bindings(params),
        },
        "provenance": _compact_optional_fields(
            {
                "execution_story_kind": metadata.get("execution_story_kind"),
                "hosted_via_br_mcp_service": bool(
                    metadata.get("hosted_via_br_mcp_service")
                ),
                "source_repo": metadata.get("source_repo"),
                "source_paper": metadata.get("source_paper"),
                "runbook": metadata.get("runbook"),
            },
            "source_repo",
            "source_paper",
        ),
        "handoff": handoff,
        "steps": [step],
    }


def _pack_handoff(
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    workflow_entry: dict[str, Any] | None,
    target_runtime: str = "python",
) -> dict[str, Any]:
    existing = metadata.get("handoff") or metadata.get("plan_handoff")
    if isinstance(existing, dict) and existing:
        return _normalize_dict(existing)
    workflow_id = str((workflow_entry or {}).get("id") or "").strip() or None
    return build_handoff_from_recipe_context(
        tool_id=tool_id,
        params=params,
        metadata=metadata,
        workflow_id=workflow_id,
        target_runtime=target_runtime,
    )


def _local_tool_pack_manifest(
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
    required_env_vars: list[str],
) -> dict[str, Any]:
    tool_manifest = {
        "tool_id": tool_id,
        "required": True,
        "schema_hash": _maybe_tool_schema_hash(
            tool_id, spec=spec, workflow_entry=workflow_entry
        ),
    }
    step = {
        "id": "run_tool",
        "label": tool_id,
        "execution_mode": "local_tool",
        "log_file": "logs/01_run_tool.json",
        "tool_manifest": tool_manifest,
        "declared_outputs": _declared_output_bindings(params, metadata),
        "provenance": {
            "kind": "local_br_tool",
            "execution_origin": "local_pack",
            "declarative_only": True,
        },
    }
    confounds_policy = _pack_confounds_policy(tool_id)
    if confounds_policy:
        step["domain_policy"] = {"confounds_non_finite": confounds_policy}
    return _base_python_pack_manifest(
        tool_id=tool_id,
        metadata=metadata,
        required_env_vars=required_env_vars,
        step=step,
        params=params,
        handoff=_pack_handoff(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            workflow_entry=workflow_entry,
        ),
    )


def _embedded_python_pack_manifest(
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    required_env_vars: list[str],
    workflow_entry: dict[str, Any] | None,
    script_name: str,
    script_text: str,
) -> dict[str, Any]:
    declared_outputs = _declared_output_bindings(params, metadata)
    step = {
        "id": "run_embedded_python",
        "label": tool_id,
        "execution_mode": "embedded_python",
        "log_file": "logs/01_run_embedded_python.json",
        "script": script_name,
        "contract_hash": _stable_json_hash(
            {
                "tool_id": tool_id,
                "script_name": script_name,
                "script": script_text,
                "declared_outputs": declared_outputs,
            }
        ),
        "declared_outputs": declared_outputs,
        "provenance": {
            "kind": "embedded_python",
            "execution_origin": "local_pack",
            "declarative_only": True,
        },
    }
    return _base_python_pack_manifest(
        tool_id=tool_id,
        metadata=metadata,
        required_env_vars=required_env_vars,
        step=step,
        params=params,
        handoff=_pack_handoff(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            workflow_entry=workflow_entry,
        ),
    )


def _generated_python_pack_runner() -> str:
    return dedent("""
        from __future__ import annotations

        import argparse
        import hashlib
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path
        from typing import Any


        PACK_MANIFEST_FILE = "pack_manifest.json"
        PACK_RUNTIME_MANIFEST_SCHEMA_VERSION = "br-pack-runtime-manifest-v1"


        def _read_json(path: Path) -> dict[str, Any]:
            return json.loads(path.read_text(encoding="utf-8"))


        def _write_json(path: Path, payload: dict[str, Any]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


        def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base)
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = _merge_dicts(merged[key], value)
                else:
                    merged[key] = value
            return merged


        def _stable_json_hash(payload: Any) -> str:
            return hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()


        def _resolve_path(base_dir: Path, value: str | None) -> Path | None:
            if not value:
                return None
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = (base_dir / candidate).resolve()
            return candidate.resolve()


        def _resolve_binding_paths(base_dir: Path, params: dict[str, Any], binding: dict[str, Any]) -> list[Path]:
            kind = str(binding.get("kind") or "").strip()
            param_name = str(binding.get("param") or "").strip()
            value = params.get(param_name)
            if kind == "param_path":
                if isinstance(value, list):
                    return [
                        resolved
                        for item in value
                        if isinstance(item, str)
                        for resolved in [_resolve_path(base_dir, item)]
                        if resolved is not None
                    ]
                if isinstance(value, str):
                    resolved = _resolve_path(base_dir, value)
                    return [resolved] if resolved is not None else []
                return []
            if kind == "output_dir_artifact" and isinstance(value, str):
                base_path = _resolve_path(base_dir, value)
                if base_path is None:
                    return []
                return [(base_path / str(binding.get("relative_path") or "")).resolve()]
            return []


        def _closest_existing_parent(path: Path) -> Path:
            current = path if path.is_dir() else path.parent
            while not current.exists() and current != current.parent:
                current = current.parent
            return current


        def _tool_schema_hash(tool: Any) -> str:
            schema_class = tool.get_args_schema()
            if hasattr(schema_class, "model_json_schema"):
                json_schema = schema_class.model_json_schema()
            else:
                json_schema = {}
            payload = {
                "tool_id": tool.get_tool_name(),
                "json_schema": json_schema,
                "required": list(json_schema.get("required") or []),
            }
            return _stable_json_hash(payload)


        def _issue(level: str, code: str, message: str, *, blocking: bool) -> dict[str, Any]:
            return {
                "level": level,
                "code": code,
                "message": message,
                "blocking": blocking,
            }


        def _run_preflight(pack_dir: Path, manifest: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
            issues: list[dict[str, Any]] = []
            blocking_levels = set(manifest.get("preflight", {}).get("blocking_levels") or [])
            advisory_levels = set(manifest.get("preflight", {}).get("advisory_levels") or [])
            del advisory_levels
            input_cache: dict[str, Any] = {}

            for env_var in manifest.get("required_env_vars") or []:
                if not os.getenv(str(env_var)):
                    issues.append(
                        _issue(
                            "L1",
                            "missing_env_var",
                            f"Required environment variable '{env_var}' is not set.",
                            blocking="L1" in blocking_levels,
                        )
                    )

            registry = None
            for step in manifest.get("steps") or []:
                if step.get("execution_mode") != "local_tool":
                    continue
                if registry is None:
                    from brain_researcher.services.tools.tool_registry import ToolRegistry

                    registry = ToolRegistry.from_env(light_mode=True)
                tool_manifest = step.get("tool_manifest") if isinstance(step, dict) else {}
                tool_id = str((tool_manifest or {}).get("tool_id") or "").strip()
                tool = registry.get_tool(tool_id) if tool_id else None
                if tool is None:
                    issues.append(
                        _issue(
                            "L1",
                            "tool_unavailable",
                            f"Declared local tool '{tool_id}' is not available in the current runtime.",
                            blocking="L1" in blocking_levels,
                        )
                    )
                    continue
                expected_hash = str((tool_manifest or {}).get("schema_hash") or "").strip()
                if expected_hash:
                    observed_hash = _tool_schema_hash(tool)
                    if observed_hash != expected_hash:
                        issues.append(
                            _issue(
                                "L1",
                                "tool_schema_mismatch",
                                (
                                    f"Tool '{tool_id}' schema hash mismatch: expected {expected_hash}, "
                                    f"observed {observed_hash}."
                                ),
                                blocking="L1" in blocking_levels,
                            )
                        )

            nifti_kinds = {"nifti_image", "nifti_list"}
            table_kinds = {"table"}
            array_kinds = {"array_or_table"}
            img_path = None
            atlas_path = None

            for binding in manifest.get("preflight", {}).get("inputs") or []:
                kind = str(binding.get("kind") or "").strip()
                param_name = str(binding.get("param") or "").strip()
                resolved_paths = _resolve_binding_paths(pack_dir, params, binding)
                if not resolved_paths:
                    continue
                for path in resolved_paths:
                    if not path.exists():
                        issues.append(
                            _issue(
                                "L1",
                                "missing_input_path",
                                f"Input path for '{param_name}' does not exist: {path}",
                                blocking="L1" in blocking_levels,
                            )
                        )
                        continue
                    if kind in nifti_kinds:
                        try:
                            import nibabel as nib

                            image = nib.load(str(path))
                            input_cache[param_name] = image
                            if param_name in {"img", "fmri_path", "func_file", "volume_img", "stat_map", "contrast_map"}:
                                img_path = path
                            if param_name in {"atlas", "atlas_path"}:
                                atlas_path = path
                        except Exception as exc:
                            issues.append(
                                _issue(
                                    "L1",
                                    "invalid_nifti",
                                    f"Failed to read NIfTI input '{param_name}' at {path}: {exc}",
                                    blocking="L1" in blocking_levels,
                                )
                            )
                    elif kind in table_kinds:
                        try:
                            import pandas as pd

                            sep = "\\t" if path.suffix.lower() == ".tsv" else ","
                            table = pd.read_csv(path, sep=sep)
                            input_cache[param_name] = table
                        except Exception as exc:
                            issues.append(
                                _issue(
                                    "L2",
                                    "invalid_table",
                                    f"Failed to parse table input '{param_name}' at {path}: {exc}",
                                    blocking="L2" in blocking_levels,
                                )
                            )
                    elif kind in array_kinds:
                        try:
                            import numpy as np

                            if path.suffix.lower() in {".csv", ".tsv", ".txt"}:
                                delimiter = "," if path.suffix.lower() == ".csv" else "\\t"
                                np.loadtxt(path, delimiter=delimiter)
                            else:
                                np.load(path)
                        except Exception as exc:
                            issues.append(
                                _issue(
                                    "L1",
                                    "invalid_array",
                                    f"Failed to load array-like input '{param_name}' at {path}: {exc}",
                                    blocking="L1" in blocking_levels,
                                )
                            )

            output_candidates = []
            output_file = params.get("output_file")
            if isinstance(output_file, str) and output_file.strip():
                resolved = _resolve_path(pack_dir, output_file)
                if resolved is not None:
                    output_candidates.append(resolved)
            output_dir = params.get("output_dir")
            if isinstance(output_dir, str) and output_dir.strip():
                resolved_dir = _resolve_path(pack_dir, output_dir)
                if resolved_dir is not None:
                    output_candidates.append(resolved_dir)
            for candidate in output_candidates:
                parent = _closest_existing_parent(candidate)
                if not os.access(parent, os.W_OK):
                    issues.append(
                        _issue(
                            "L1",
                            "output_not_writable",
                            f"Output location is not writable: {candidate}",
                            blocking="L1" in blocking_levels,
                        )
                    )

            has_filter = any(
                params.get(name) is not None for name in ("high_pass", "low_pass")
            )
            has_tr = any(params.get(name) is not None for name in ("t_r", "tr", "repetition_time"))
            image_for_tr = input_cache.get("img")
            if has_filter and not has_tr and image_for_tr is not None:
                zooms = image_for_tr.header.get_zooms()
                if len(zooms) < 4:
                    issues.append(
                        _issue(
                            "L2",
                            "missing_tr",
                            "Filtering is requested but TR cannot be inferred from the input image header.",
                            blocking="L2" in blocking_levels,
                        )
                    )

            if img_path is not None and atlas_path is not None:
                img = input_cache.get("img")
                atlas = input_cache.get("atlas") or input_cache.get("atlas_path")
                if img is not None and atlas is not None:
                    if tuple(img.shape[:3]) != tuple(atlas.shape[:3]):
                        issues.append(
                            _issue(
                                "L2",
                                "atlas_bold_shape_mismatch",
                                (
                                    "Atlas and image have incompatible spatial shapes: "
                                    f"{tuple(img.shape[:3])} vs {tuple(atlas.shape[:3])}."
                                ),
                                blocking="L2" in blocking_levels,
                            )
                        )

            confounds_table = input_cache.get("confounds") or input_cache.get("confounds_file")
            confounds_policy = None
            for step in manifest.get("steps") or []:
                domain_policy = step.get("domain_policy") if isinstance(step, dict) else {}
                if isinstance(domain_policy, dict) and domain_policy.get("confounds_non_finite"):
                    confounds_policy = str(domain_policy.get("confounds_non_finite"))
            if confounds_table is not None:
                numeric = confounds_table.select_dtypes(include=["number"])
                if not numeric.empty:
                    import numpy as np

                    invalid = ~np.isfinite(numeric.to_numpy(dtype=float, copy=False))
                    if invalid.any():
                        columns = numeric.columns[invalid.any(axis=0)].tolist()
                        if confounds_policy == "sanitize_non_finite_to_zero":
                            issues.append(
                                _issue(
                                    "L2",
                                    "confounds_non_finite_handled",
                                    (
                                        "Confounds contain non-finite values, but the pack declares "
                                        f"policy '{confounds_policy}' for columns {columns}."
                                    ),
                                    blocking=False,
                                )
                            )
                        else:
                            issues.append(
                                _issue(
                                    "L2",
                                    "confounds_non_finite",
                                    (
                                        "Confounds contain non-finite values and no sanitizer policy "
                                        f"is declared. Columns: {columns}"
                                    ),
                                    blocking="L2" in blocking_levels,
                                )
                            )

            if img_path is not None:
                try:
                    size_gb = img_path.stat().st_size / (1024 ** 3)
                    profile = manifest.get("resource_profile") if isinstance(manifest.get("resource_profile"), dict) else {}
                    est = profile.get("est_runtime")
                    if size_gb >= 0.5 or est:
                        issues.append(
                            _issue(
                                "L3",
                                "resource_estimate",
                                (
                                    f"Input image is approximately {size_gb:.2f} GiB. "
                                    f"Declared resource profile: {profile or {'est_runtime': est}}"
                                ),
                                blocking=False,
                            )
                        )
                except FileNotFoundError:
                    pass

            blocking_issues = [issue for issue in issues if issue.get("blocking")]
            return {
                "schema_version": "br-pack-preflight-v1",
                "passed": not blocking_issues,
                "issues": issues,
                "blocking_issue_count": len(blocking_issues),
            }


        def _tool_result_to_dict(result: Any) -> dict[str, Any]:
            if hasattr(result, "model_dump"):
                return result.model_dump(mode="python")
            if isinstance(result, dict):
                return result
            return {"status": "success", "data": result}


        def _extract_outputs(payload: dict[str, Any]) -> dict[str, Any]:
            if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("outputs"), dict):
                return dict(payload["data"]["outputs"])
            if isinstance(payload.get("outputs"), dict):
                return dict(payload["outputs"])
            return {}


        def _step_log_path(pack_dir: Path, step: dict[str, Any]) -> Path:
            return (pack_dir / str(step.get("log_file") or f"logs/{step.get('id')}.json")).resolve()


        def _declared_output_paths(pack_dir: Path, params: dict[str, Any], step: dict[str, Any]) -> list[Path]:
            paths: list[Path] = []
            for binding in step.get("declared_outputs") or []:
                paths.extend(_resolve_binding_paths(pack_dir, params, binding))
            deduped: list[Path] = []
            seen: set[Path] = set()
            for path in paths:
                if path in seen:
                    continue
                seen.add(path)
                deduped.append(path)
            return deduped


        def _can_resume(pack_dir: Path, params: dict[str, Any], step: dict[str, Any]) -> bool:
            log_path = _step_log_path(pack_dir, step)
            if not log_path.exists():
                return False
            try:
                payload = _read_json(log_path)
            except Exception:
                return False
            if str(payload.get("status") or "").strip() != "success":
                return False
            outputs = _declared_output_paths(pack_dir, params, step)
            if not outputs:
                return False
            return all(path.exists() for path in outputs)


        def _run_local_tool_step(step: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
            from brain_researcher.services.tools.runner import execute_tool

            tool_id = str(step.get("tool_manifest", {}).get("tool_id") or "").strip()
            return _tool_result_to_dict(execute_tool(tool_id, params))


        def _run_embedded_python_step(
            pack_dir: Path,
            step: dict[str, Any],
            params: dict[str, Any],
            params_file: Path,
        ) -> dict[str, Any]:
            script_name = str(step.get("script") or "").strip()
            if not script_name:
                raise RuntimeError(f"Embedded step {step.get('id')} is missing a script.")
            params_json_path = pack_dir / "params.json"
            original_params_text = (
                params_json_path.read_text(encoding="utf-8")
                if params_json_path.exists()
                else None
            )
            params_json_path.write_text(
                json.dumps(params, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            try:
                proc = subprocess.run(
                    [sys.executable, script_name],
                    cwd=str(pack_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                    env=os.environ.copy(),
                )
            finally:
                if original_params_text is not None:
                    params_json_path.write_text(
                        original_params_text, encoding="utf-8"
                    )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            if proc.returncode != 0:
                return {
                    "status": "error",
                    "error": f"Embedded script exited with code {proc.returncode}",
                    "data": {
                        "stdout": stdout,
                        "stderr": stderr,
                        "params_file": str(params_file),
                    },
                }
            if not stdout:
                return {
                    "status": "error",
                    "error": "Embedded script did not emit JSON output.",
                    "data": {
                        "stderr": stderr,
                        "params_file": str(params_file),
                    },
                }
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError as exc:
                return {
                    "status": "error",
                    "error": f"Embedded script emitted non-JSON stdout: {exc}",
                    "data": {
                        "stdout": stdout,
                        "stderr": stderr,
                        "params_file": str(params_file),
                    },
                }
            return {
                "status": "success",
                "data": payload,
                "stdout": stdout,
                "stderr": stderr,
            }


        def _run_step(pack_dir: Path, step: dict[str, Any], params: dict[str, Any], params_file: Path) -> dict[str, Any]:
            mode = str(step.get("execution_mode") or "").strip()
            if mode == "local_tool":
                return _run_local_tool_step(step, params)
            if mode == "embedded_python":
                return _run_embedded_python_step(pack_dir, step, params, params_file)
            raise RuntimeError(f"Unsupported execution_mode: {mode}")


        def _runtime_manifest(
            pack_dir: Path,
            manifest: dict[str, Any],
            params_file: Path,
            effective_params_path: Path,
            preflight_report: dict[str, Any],
            step_records: list[dict[str, Any]],
        ) -> dict[str, Any]:
            return {
                "schema_version": PACK_RUNTIME_MANIFEST_SCHEMA_VERSION,
                "pack_id": manifest.get("pack_id"),
                "tool_id": manifest.get("tool_id"),
                "target_runtime": manifest.get("target_runtime"),
                "workspace_root": str(pack_dir),
                "params_file": str(params_file),
                "effective_params": str(effective_params_path),
                "preflight": preflight_report,
                "steps": step_records,
                "step_logs": {
                    record["id"]: record["log_file"]
                    for record in step_records
                },
            }


        def parse_args() -> argparse.Namespace:
            parser = argparse.ArgumentParser(description="Run a Brain Researcher local execution pack.")
            parser.add_argument("--params", default="params.json", help="Optional override params file.")
            parser.add_argument("--dry-run", action="store_true", help="Write effective params and exit.")
            parser.add_argument("--preflight", action="store_true", help="Run preflight only.")
            parser.add_argument("--force", action="store_true", help="Ignore resume and rerun all steps.")
            return parser.parse_args()


        def main() -> None:
            args = parse_args()
            pack_dir = Path(__file__).resolve().parent
            manifest = _read_json(pack_dir / PACK_MANIFEST_FILE)
            base_params = _read_json(pack_dir / "params.json")
            params_path = _resolve_path(pack_dir, args.params)
            override_params = (
                _read_json(params_path)
                if params_path is not None and params_path.exists() and params_path.name != "params.json"
                else {}
            )
            effective_params = _merge_dicts(base_params, override_params)
            effective_params_path = (pack_dir / "effective_params.json").resolve()
            _write_json(effective_params_path, effective_params)

            preflight_report = _run_preflight(pack_dir, manifest, effective_params)
            if args.dry_run:
                print(json.dumps({
                    "status": "dry_run",
                    "pack_manifest": str((pack_dir / PACK_MANIFEST_FILE).resolve()),
                    "effective_params": str(effective_params_path),
                    "preflight": preflight_report,
                }, indent=2, sort_keys=True))
                return
            if args.preflight:
                print(json.dumps(preflight_report, indent=2, sort_keys=True))
                raise SystemExit(0 if preflight_report.get("passed") else 1)
            if not preflight_report.get("passed"):
                print(json.dumps(preflight_report, indent=2, sort_keys=True))
                raise SystemExit(1)

            step_records: list[dict[str, Any]] = []
            for step in manifest.get("steps") or []:
                log_path = _step_log_path(pack_dir, step)
                if not args.force and _can_resume(pack_dir, effective_params, step):
                    step_records.append(
                        {
                            "id": step.get("id"),
                            "status": "skipped",
                            "reason": "resume_from_success_log",
                            "log_file": str(log_path),
                            "declared_outputs": [str(path) for path in _declared_output_paths(pack_dir, effective_params, step)],
                        }
                    )
                    continue

                payload = _run_step(pack_dir, step, effective_params, effective_params_path)
                _write_json(log_path, payload)
                if str(payload.get("status") or "").strip() != "success":
                    runtime_manifest = _runtime_manifest(
                        pack_dir,
                        manifest,
                        params_path or (pack_dir / "params.json"),
                        effective_params_path,
                        preflight_report,
                        step_records
                        + [
                            {
                                "id": step.get("id"),
                                "status": "error",
                                "log_file": str(log_path),
                                "declared_outputs": [str(path) for path in _declared_output_paths(pack_dir, effective_params, step)],
                            }
                        ],
                    )
                    _write_json(pack_dir / "manifest.json", runtime_manifest)
                    raise RuntimeError(
                        f"Step {step.get('id')} failed: {payload.get('error') or payload}"
                    )

                step_records.append(
                    {
                        "id": step.get("id"),
                        "status": "success",
                        "log_file": str(log_path),
                        "declared_outputs": [str(path) for path in _declared_output_paths(pack_dir, effective_params, step)],
                        "outputs": _extract_outputs(payload),
                    }
                )

            runtime_manifest = _runtime_manifest(
                pack_dir,
                manifest,
                params_path or (pack_dir / "params.json"),
                effective_params_path,
                preflight_report,
                step_records,
            )
            _write_json(pack_dir / "manifest.json", runtime_manifest)
            print(json.dumps(runtime_manifest, indent=2, sort_keys=True))


        if __name__ == "__main__":
            main()
        """).lstrip()


def _attach_python_pack_contract(
    recipe: dict[str, Any],
    *,
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
    execution_mode: str,
    script_name: str | None = None,
) -> dict[str, Any]:
    files = dict(recipe.get("files") or {})
    required_env_vars = [
        str(name).strip()
        for name in (recipe.get("required_env_vars") or [])
        if str(name).strip()
    ]
    if execution_mode == "embedded_python":
        if not script_name or script_name not in files:
            raise ValueError(
                f"Embedded python pack for '{tool_id}' requires script '{script_name}'."
            )
        manifest = _embedded_python_pack_manifest(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            required_env_vars=required_env_vars,
            workflow_entry=workflow_entry,
            script_name=script_name,
            script_text=str(files[script_name]),
        )
    else:
        manifest = _local_tool_pack_manifest(
            tool_id=tool_id,
            params=params,
            metadata=metadata,
            spec=spec,
            workflow_entry=workflow_entry,
            required_env_vars=required_env_vars,
        )
    files[_PACK_MANIFEST_FILE] = _json_text(manifest)
    files[_PACK_RUNNER_FILE] = _generated_python_pack_runner()
    recipe["files"] = files
    recipe["pack_contract"] = manifest
    recipe["run_pack_command"] = f"python {_PACK_RUNNER_FILE}"
    return recipe


def _python_setup_commands(
    python_packages: list[str],
    *,
    repo_env_var: str = "BRAIN_RESEARCHER_REPO",
) -> tuple[list[str], list[str]]:
    packages = [str(pkg).strip() for pkg in python_packages if str(pkg).strip()]
    commands = [
        "python -m venv .venv",
        ". .venv/bin/activate",
        "python -m pip install --upgrade pip",
    ]
    required_env_vars: list[str] = []
    repo_packages = [pkg for pkg in packages if pkg == "brain_researcher"]
    extra_packages = [pkg for pkg in packages if pkg != "brain_researcher"]
    if repo_packages:
        required_env_vars.append(repo_env_var)
        extras = (
            " " + " ".join(shlex.quote(pkg) for pkg in extra_packages)
            if extra_packages
            else ""
        )
        commands.append(f'pip install -e "${{{repo_env_var}}}"{extras}')
    elif extra_packages:
        commands.append(
            "pip install " + " ".join(shlex.quote(pkg) for pkg in extra_packages)
        )
    return commands, required_env_vars


_RUN_PACK_ENV_HINTS: dict[str, dict[str, Any]] = {
    "FS_LICENSE": {
        "kind": "path",
        "secret": False,
        "description": "Path to a FreeSurfer license.txt file.",
        "example": "/path/to/license.txt",
        "how_to_get": "Register at https://surfer.nmr.mgh.harvard.edu/registration.html",
    },
    "BRAIN_RESEARCHER_REPO": {
        "kind": "path",
        "secret": False,
        "description": "Absolute path to a local checkout of the brain_researcher repository.",
        "example": "/abs/path/to/brain_researcher",
        "how_to_get": "Point this to your local clone of the repository before running the recipe.",
    },
}


def _run_pack_environment(required_env_vars: list[str]) -> dict[str, Any]:
    required: list[dict[str, Any]] = []
    for name in required_env_vars:
        hint = dict(_RUN_PACK_ENV_HINTS.get(name, {}))
        required.append(
            {
                "name": name,
                "required": True,
                "kind": hint.get("kind", "string"),
                "secret": bool(hint.get("secret", False)),
                "description": hint.get(
                    "description", f"Set {name} before running this recipe."
                ),
                "example": hint.get("example", "<set-me>"),
                "how_to_get": hint.get("how_to_get"),
                "export_line": f'export {name}="<set-me>"',
            }
        )
    return {
        "required": required,
        "optional": [],
        "export_lines": _env_exports(required_env_vars),
    }


def _run_pack_prerequisites(
    *,
    target_runtime: str,
    required_env_vars: list[str],
) -> dict[str, list[str]]:
    normalized_target = normalize_recipe_target(target_runtime)
    setup_once: list[str] = []
    checks: list[str] = []
    if normalized_target == "python":
        setup_once.append(
            "Create or activate a local conda environment or Python venv before running the recipe commands."
        )
        checks.append("python --version")
    elif normalized_target == "neurodesk":
        setup_once.append(
            "Open a Neurodesk shell with the required modules available before running the recipe commands."
        )
        checks.append("bash -lc 'type module'")
    elif normalized_target == "container":
        setup_once.append(
            "Install Docker or a compatible container runtime before running the recipe commands."
        )
        checks.append("docker --version")
    elif normalized_target == "slurm":
        setup_once.append(
            "Run from a cluster login node with scheduler access before submitting the recipe."
        )
        checks.append("command -v sbatch")

    for name in required_env_vars:
        if name == "FS_LICENSE":
            checks.append('test -f "$FS_LICENSE"')
        elif name == "BRAIN_RESEARCHER_REPO":
            checks.append('test -d "$BRAIN_RESEARCHER_REPO"')
        else:
            checks.append(f'test -n "${name}"')

    return {
        "setup_once": _dedupe(setup_once),
        "check_commands": _dedupe(checks),
    }


def _recipe_run_pack_payload(
    tool_id: str,
    target_runtime: str,
    recipe: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(recipe, dict):
        return None
    files = recipe.get("files")
    if not isinstance(files, dict) or not files:
        return None

    normalized_target = normalize_recipe_target(target_runtime)
    workspace = f"./{_slugify(tool_id)}_{normalized_target}_recipe"
    write_files = [str(name) for name in files.keys()]
    shell_files = [name for name in write_files if name.endswith(".sh")]
    required_env_vars = [
        str(name).strip()
        for name in (recipe.get("required_env_vars") or [])
        if str(name).strip()
    ]
    if any(
        "${BRAIN_RESEARCHER_REPO}" in str(cmd)
        for cmd in (recipe.get("setup_commands") or [])
    ):
        if "BRAIN_RESEARCHER_REPO" not in required_env_vars:
            required_env_vars.append("BRAIN_RESEARCHER_REPO")
    env_exports = _env_exports(required_env_vars)
    commands: list[str] = []
    if shell_files:
        commands.append(
            "chmod +x " + " ".join(shlex.quote(name) for name in shell_files)
        )
    commands.extend(
        str(item).strip()
        for item in (recipe.get("setup_commands") or [])
        if str(item).strip()
    )
    run_command = str(recipe.get("run_command") or "").strip()
    run_pack_command = str(recipe.get("run_pack_command") or "").strip()
    if run_pack_command:
        commands.append(run_pack_command)
    elif run_command:
        commands.append(run_command)

    shell_lines = [
        "# Write recipe['files'] into this directory first.",
        f"mkdir -p {shlex.quote(workspace)}",
        f"cd {shlex.quote(workspace)}",
        *(
            ["# Required environment variables:"]
            + [f"# {line}" for line in env_exports]
            if env_exports
            else []
        ),
        *commands,
    ]
    materialize_python = dedent(f"""
        from pathlib import Path

        recipe_resp = ...  # JSON returned by get_execution_recipe(...)
        recipe = recipe_resp["recipe"]
        workspace = Path({workspace!r})
        workspace.mkdir(parents=True, exist_ok=True)

        for name, text in recipe["files"].items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            if path.suffix == ".sh":
                path.chmod(path.stat().st_mode | 0o111)

        print("Wrote recipe files to", workspace)
        if {env_exports!r}:
            print("Set required environment variables before running:")
            for line in {env_exports!r}:
                print(line)
        print("Run locally:")
        for cmd in {commands!r}:
            print(cmd)
        """).strip()

    pack_contract = (
        recipe.get("pack_contract")
        if isinstance(recipe.get("pack_contract"), dict)
        else {}
    )
    preflight_contract = (
        pack_contract.get("preflight")
        if isinstance(pack_contract.get("preflight"), dict)
        else {}
    )

    return {
        "schema_version": "1",
        "runtime": {
            "target": normalized_target,
            "launcher": "shell_script" if shell_files else "command",
        },
        "workspace": workspace,
        "write_files": write_files,
        "commands": commands,
        "entrypoint": _PACK_RUNNER_FILE if _PACK_RUNNER_FILE in write_files else None,
        "pack_manifest_file": (
            _PACK_MANIFEST_FILE if _PACK_MANIFEST_FILE in write_files else None
        ),
        "handoff": (
            _normalize_dict(pack_contract.get("handoff"))
            if isinstance(pack_contract.get("handoff"), dict)
            else None
        ),
        "resume_supported": bool(pack_contract),
        "preflight": (
            {
                "blocking_levels": _normalize_list(
                    preflight_contract.get("blocking_levels")
                ),
                "advisory_levels": _normalize_list(
                    preflight_contract.get("advisory_levels")
                ),
            }
            if pack_contract
            else None
        ),
        "prerequisites": _run_pack_prerequisites(
            target_runtime=normalized_target,
            required_env_vars=required_env_vars,
        ),
        "environment": _run_pack_environment(required_env_vars),
        "required_env_vars": required_env_vars,
        "env_exports": env_exports,
        "shell_snippet": "\n".join(shell_lines),
        "materialize_python": materialize_python,
    }


def _recipe_local_run_payload(
    tool_id: str,
    target_runtime: str,
    recipe: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _recipe_run_pack_payload(tool_id, target_runtime, recipe)


def materialize_recipe_files(recipe: dict[str, Any], workspace: str | Path) -> Path:
    """Write recipe files into ``workspace`` and return the resolved path."""
    files = recipe.get("files") if isinstance(recipe, dict) else None
    if not isinstance(files, dict) or not files:
        raise ValueError("Recipe does not contain any materializable files.")

    workspace_path = Path(workspace).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)

    for relpath, text in files.items():
        path = workspace_path / str(relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding="utf-8")
        if path.suffix == ".sh":
            path.chmod(path.stat().st_mode | 0o111)

    return workspace_path


def materialize_execution_pack(
    tool_id: str,
    params: dict[str, Any],
    workspace: str | Path,
    *,
    target_runtime: str | None = None,
) -> dict[str, Any]:
    """Build and write a local execution pack for a tool invocation."""
    normalized_target = normalize_recipe_target(
        target_runtime or default_recipe_target(tool_id)
    )
    payload = build_execution_recipe(
        tool_id=tool_id,
        params=params,
        target_runtime=normalized_target,
    )
    recipe = payload.get("recipe")
    if not isinstance(recipe, dict) or not recipe:
        message = str(payload.get("message") or "No execution recipe available.")
        error = str(payload.get("error") or "").strip()
        if error:
            message = f"{message} ({error})"
        raise ValueError(message)

    workspace_path = materialize_recipe_files(recipe, workspace)
    files = recipe.get("files")
    assert isinstance(files, dict)

    pack_manifest = workspace_path / _PACK_MANIFEST_FILE
    run_pack = workspace_path / _PACK_RUNNER_FILE

    return {
        "tool_id": tool_id,
        "target_runtime": normalized_target,
        "workspace": str(workspace_path),
        "files_written": sorted(str(name) for name in files.keys()),
        "pack_manifest": (
            str(pack_manifest.resolve()) if pack_manifest.exists() else None
        ),
        "run_pack": str(run_pack.resolve()) if run_pack.exists() else None,
        "run_pack_command": str(recipe.get("run_pack_command") or "").strip() or None,
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        ordered.append(value)
        seen.add(value)
    return ordered


def _step_tools(workflow_entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    runtime = (
        workflow_entry.get("runtime") if isinstance(workflow_entry, dict) else None
    )
    steps = runtime.get("steps") if isinstance(runtime, dict) else None
    return [step for step in (steps or []) if isinstance(step, dict)]


@lru_cache(maxsize=1)
def _raw_workflow_catalog_index() -> dict[str, dict[str, Any]]:
    workflow_path = (
        execution_recipe_config_path().parents[1]
        / "workflows"
        / "workflow_catalog.yaml"
    )
    if not workflow_path.exists():
        return {}
    try:
        import yaml

        payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    workflows = payload.get("workflows") if isinstance(payload, dict) else None
    if not isinstance(workflows, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in workflows:
        if not isinstance(row, dict):
            continue
        workflow_id = str(row.get("id") or "").strip()
        if workflow_id:
            indexed[workflow_id] = row
    return indexed


def _workflow_uses_bids_apps(
    workflow_entry: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    apps: list[str] = []
    for step in _step_tools(workflow_entry):
        if str(step.get("tool") or "").strip() != "run_bids_app":
            continue
        params = step.get("params")
        app = str((params or {}).get("app") or "").strip().lower()
        if app:
            apps.append(app)
    return bool(apps), _dedupe(apps)


@lru_cache(maxsize=1)
def _all_toolspecs_by_name() -> dict[str, ToolSpec]:
    """Best-effort toolspec index for workflow step classification."""

    try:
        from brain_researcher.services.tools.catalog_loader import load_tool_specs
    except Exception:
        return {}

    try:
        loaded = load_tool_specs(force_reload=False, exposed_only=False)
    except Exception:
        return {}

    if isinstance(loaded, dict):
        specs = loaded.values()
    else:
        specs = loaded

    indexed: dict[str, ToolSpec] = {}
    for spec in specs:
        name = str(getattr(spec, "name", "") or "").strip()
        if name:
            indexed[name] = spec
    return indexed


def _workflow_recipe_analysis(workflow_entry: dict[str, Any] | None) -> dict[str, Any]:
    workflow_id = str((workflow_entry or {}).get("id") or "").strip()
    step_names = [
        str(step.get("tool") or "").strip().lower()
        for step in _step_tools(workflow_entry)
        if str(step.get("tool") or "").strip()
    ]
    indexed_specs = _all_toolspecs_by_name()

    external_steps: list[str] = []
    unknown_steps: list[str] = []
    for step_name in step_names:
        if step_name in _HEAVY_WORKFLOW_STEPS or any(
            step_name.startswith(prefix) for prefix in _NON_PORTABLE_STEP_PREFIXES
        ):
            external_steps.append(step_name)
            continue

        spec = indexed_specs.get(step_name)
        if spec is None:
            unknown_steps.append(step_name)
            continue

        runtime = infer_requires_runtime(spec.requires_runtime, backend=spec.backend)
        backend = str(spec.backend or "").strip().lower()
        if runtime == "container" or backend == "niwrap":
            external_steps.append(step_name)

    cost_tier = str((workflow_entry or {}).get("cost_tier") or "").strip().lower()
    declared_targets = _normalize_list(
        (workflow_entry or {}).get("supported_recipe_targets")
    )
    declares_python = "python" in declared_targets
    python_safe = (
        bool(step_names)
        and not external_steps
        and not unknown_steps
        and (
            workflow_id in _DIRECT_PYTHON_WORKFLOWS
            or cost_tier != "expensive"
            or declares_python
        )
    )
    return {
        "workflow_id": workflow_id,
        "step_names": step_names,
        "external_steps": _dedupe(external_steps),
        "unknown_steps": _dedupe(unknown_steps),
        "python_safe": python_safe,
    }


def _declared_story_kind(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in EXECUTION_STORY_KINDS else ""


def _declared_recipe_metadata(
    tool_id: str,
    *,
    override: dict[str, Any],
    workflow_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    tool_declaration = get_tool_recipe_declaration(tool_id)
    declaration_sources: list[tuple[str, dict[str, Any]]] = []
    raw_workflow_entry = _raw_workflow_catalog_index().get(str(tool_id or "").strip())
    if isinstance(raw_workflow_entry, dict):
        declaration_sources.append(("workflow_catalog", raw_workflow_entry))
    if isinstance(workflow_entry, dict):
        declaration_sources.append(("workflow_catalog_entry", workflow_entry))
    if tool_declaration:
        declaration_sources.append(("tool_declarations", tool_declaration))
    if override:
        declaration_sources.append(("tool_overrides", override))

    story_kind = ""
    story_source = ""
    supported_targets: list[str] | None = None
    targets_source = ""
    primary_target: str | None = None
    primary_source = ""
    recipe_family = ""
    family_source = ""
    stable_workflow_pack = False
    source_repo = None
    source_paper = None
    tested_release = None
    backend_options = None
    example_dataset = None
    reference_assets = None
    artifact_contract = None
    acceptance_gate = None
    runbook = None
    python_packages = None
    required_env_vars = None
    resource_profile = None

    for source_name, payload in declaration_sources:
        if not story_kind:
            candidate = _declared_story_kind(payload.get("execution_story_kind"))
            if candidate:
                story_kind = candidate
                story_source = source_name

        if supported_targets is None and "supported_recipe_targets" in payload:
            supported_targets = _normalize_list(payload.get("supported_recipe_targets"))
            targets_source = source_name

        if primary_target is None and "primary_target" in payload:
            primary_target = normalize_recipe_target(payload.get("primary_target"))
            primary_source = source_name

        if not recipe_family:
            candidate_family = str(payload.get("recipe_family") or "").strip()
            if candidate_family:
                recipe_family = candidate_family
                family_source = source_name

        if not stable_workflow_pack and payload.get("stable_workflow_pack") is not None:
            stable_workflow_pack = bool(payload.get("stable_workflow_pack"))
        if source_repo is None and payload.get("source_repo") is not None:
            source_repo = payload.get("source_repo")
        if source_paper is None and payload.get("source_paper") is not None:
            source_paper = payload.get("source_paper")
        if tested_release is None and payload.get("tested_release") is not None:
            tested_release = payload.get("tested_release")
        if backend_options is None and payload.get("backend_options") is not None:
            backend_options = payload.get("backend_options")
        if example_dataset is None and payload.get("example_dataset") is not None:
            example_dataset = payload.get("example_dataset")
        if reference_assets is None and payload.get("reference_assets") is not None:
            reference_assets = payload.get("reference_assets")
        if artifact_contract is None and payload.get("artifact_contract") is not None:
            artifact_contract = payload.get("artifact_contract")
        if acceptance_gate is None and payload.get("acceptance_gate") is not None:
            acceptance_gate = payload.get("acceptance_gate")
        if runbook is None and payload.get("runbook") is not None:
            runbook = payload.get("runbook")
        if python_packages is None and payload.get("python_packages") is not None:
            python_packages = payload.get("python_packages")
        if required_env_vars is None and payload.get("required_env_vars") is not None:
            required_env_vars = payload.get("required_env_vars")
        if resource_profile is None and payload.get("resource_profile") is not None:
            resource_profile = payload.get("resource_profile")

    return {
        "execution_story_kind": story_kind,
        "supported_recipe_targets": supported_targets,
        "primary_target": primary_target,
        "recipe_family": recipe_family,
        "stable_workflow_pack": stable_workflow_pack,
        "source_repo": source_repo,
        "source_paper": source_paper,
        "tested_release": tested_release,
        "backend_options": backend_options,
        "example_dataset": example_dataset,
        "reference_assets": reference_assets,
        "artifact_contract": artifact_contract,
        "acceptance_gate": acceptance_gate,
        "runbook": runbook,
        "python_packages": _normalize_list(python_packages),
        "required_env_vars": _normalize_list(required_env_vars),
        "resource_profile": _normalize_dict(resource_profile),
        "story_source": story_source,
        "targets_source": targets_source,
        "primary_source": primary_source,
        "family_source": family_source,
        "has_declared_story_kind": bool(story_kind),
        "has_declared_supported_recipe_targets": supported_targets is not None,
        "has_declared_primary_target": primary_target is not None,
        "has_declared_recipe_metadata": bool(story_kind)
        and supported_targets is not None
        and primary_target is not None,
    }


def _infer_supported_targets(
    tool_id: str,
    *,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
) -> list[str]:
    lowered = str(tool_id or "").lower()
    if lowered in _HOSTED_TOOL_IDS:
        return []
    if isinstance(workflow_entry, dict):
        analysis = _workflow_recipe_analysis(workflow_entry)
        uses_bids_apps, apps = _workflow_uses_bids_apps(workflow_entry)
        if uses_bids_apps and any(app in _BIDS_APPS for app in apps):
            return ["neurodesk", "container", "slurm"]
        if analysis["external_steps"]:
            return ["neurodesk", "container", "slurm"]
        if analysis["python_safe"]:
            return ["python"]
        return []

    runtime = infer_requires_runtime(
        spec.requires_runtime if spec is not None else None,
        backend=spec.backend if spec is not None else None,
    )
    package_profile = _resolve_neurodesk_package_profile(tool_id)
    if any(lowered.startswith(prefix) for prefix in _NEURODESK_PREFIX_MAP):
        return ["neurodesk", "container", "slurm"]
    if package_profile is not None:
        targets = ["neurodesk", "slurm"]
        if get_container_image(package_profile.get("name")):
            targets.insert(1, "container")
        return _dedupe(targets)
    if runtime == "container":
        return ["neurodesk", "container", "slurm"]
    if runtime == "network":
        return []
    if runtime == "none":
        return []
    return ["python"]


def _infer_neurodesk_modules(
    tool_id: str,
    *,
    workflow_entry: dict[str, Any] | None,
) -> list[str]:
    modules: list[str] = []
    if isinstance(workflow_entry, dict):
        uses_bids_apps, apps = _workflow_uses_bids_apps(workflow_entry)
        if uses_bids_apps:
            for app in apps:
                profile = get_neurodesk_package_profile(app)
                if isinstance(profile, dict):
                    modules.append(f"{profile['module_name']}/{profile['version']}")
            if any(app in {"fmriprep", "qsiprep"} for app in apps):
                fs = get_neurodesk_package_profile("freesurfer")
                if isinstance(fs, dict):
                    modules.append(f"{fs['module_name']}/{fs['version']}")
            return _dedupe(modules)

        step_names = {
            str(step.get("tool") or "").strip().lower()
            for step in _step_tools(workflow_entry)
        }
        if (
            "run_tractography" in step_names
            or "build_structural_connectome" in step_names
        ):
            for name in ("mrtrix3", "ants", "freesurfer"):
                profile = get_neurodesk_package_profile(name)
                if isinstance(profile, dict):
                    modules.append(f"{profile['module_name']}/{profile['version']}")
            return _dedupe(modules)

    module_resolution = _neurodesk_module_resolution(tool_id)
    recommended_module = str(
        module_resolution.get("neurodesk_recommended_module") or ""
    ).strip()
    if recommended_module:
        return [recommended_module]
    return []


def _infer_python_packages(
    tool_id: str,
    *,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
) -> list[str]:
    packages = ["brain_researcher"]
    name = str(tool_id or "").lower()
    if name == "kg_multihop_qa" or (
        spec is not None and (spec.kind or "").lower() == "kg"
    ):
        packages.append("neo4j>=5.28.0")
    if isinstance(workflow_entry, dict):
        workflow_id = str(workflow_entry.get("id") or "").strip()
        if workflow_id == "workflow_rest_connectome_e2e":
            packages.extend(
                [
                    "nibabel>=5.0.0",
                    "nilearn>=0.10.0",
                    "numpy>=1.24.0",
                    "pandas>=2.2.0",
                    "scikit-learn>=1.3.0",
                ]
            )
        elif workflow_id == "workflow_seed_based_connectivity":
            packages.extend(
                [
                    "nibabel>=5.0.0",
                    "nilearn>=0.10.0",
                    "numpy>=1.24.0",
                    "pandas>=2.2.0",
                ]
            )
        elif workflow_id == "workflow_network_based_statistics":
            packages.extend(
                [
                    "nibabel>=5.0.0",
                    "nilearn>=0.10.0",
                    "numpy>=1.24.0",
                    "pandas>=2.2.0",
                    "scipy>=1.11.0",
                ]
            )
        elif workflow_id == "workflow_connectivity_gradients":
            packages.extend(
                [
                    "nibabel>=5.0.0",
                    "nilearn>=0.10.0",
                    "numpy>=1.24.0",
                    "pandas>=2.2.0",
                ]
            )
        elif workflow_id == "workflow_group_ica":
            packages.extend(
                [
                    "nibabel>=5.0.0",
                    "nilearn>=0.10.0",
                    "numpy>=1.24.0",
                    "pandas>=2.2.0",
                    "scikit-learn>=1.3.0",
                    "scipy>=1.11.0",
                ]
            )
        elif workflow_id == "workflow_dwi_connectome":
            packages.extend(
                [
                    "nibabel>=5.0.0",
                    "numpy>=1.24.0",
                    "pandas>=2.2.0",
                    "scipy>=1.11.0",
                ]
            )
    return _dedupe(packages)


def _direct_family_python_packages(recipe_family: str) -> list[str]:
    if recipe_family == "glm":
        return [
            "nibabel>=5.0.0",
            "nilearn>=0.10.0",
            "numpy>=1.24.0",
            "pandas>=2.2.0",
        ]
    if recipe_family in {"connectivity_matrix", "seed_based_connectivity"}:
        return [
            "nibabel>=5.0.0",
            "nilearn>=0.10.0",
            "numpy>=1.24.0",
            "pandas>=2.2.0",
        ]
    if recipe_family == "mvpa":
        return [
            "nibabel>=5.0.0",
            "nilearn>=0.10.0",
            "numpy>=1.24.0",
            "scikit-learn>=1.3.0",
        ]
    if recipe_family == "temporal_decoding":
        return [
            "numpy>=1.24.0",
            "scikit-learn>=1.3.0",
        ]
    if recipe_family == "encoding_models":
        return [
            "numpy>=1.24.0",
            "scikit-learn>=1.3.0",
        ]
    if recipe_family == "searchlight":
        return [
            "matplotlib>=3.7.0",
            "nibabel>=5.0.0",
            "nilearn>=0.10.0",
            "numpy>=1.24.0",
            "scikit-learn>=1.3.0",
            "scipy>=1.11.0",
        ]
    return []


def _infer_required_env_vars(
    tool_id: str,
    *,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
) -> list[str]:
    env_vars: list[str] = []
    caps = spec.execution_capabilities if spec is not None else None
    if isinstance(caps, ToolExecutionCapabilities):
        env_vars.extend(_normalize_list(caps.needs_secrets))
    name = str(tool_id or "").lower()
    if name == "kg_multihop_qa":
        env_vars.extend(["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"])
    uses_bids_apps, apps = _workflow_uses_bids_apps(workflow_entry)
    if uses_bids_apps and any(app in {"fmriprep", "qsiprep"} for app in apps):
        env_vars.append("FS_LICENSE")
    if "workflow_dwi_connectome" == str((workflow_entry or {}).get("id") or ""):
        env_vars.append("FS_LICENSE")
    return _dedupe(env_vars)


def _infer_resource_profile(
    *,
    tool_id: str,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
    override: dict[str, Any],
) -> dict[str, Any]:
    override_profile = _normalize_dict(override.get("resource_profile"))
    if override_profile:
        return override_profile

    if isinstance(workflow_entry, dict):
        cost = str(workflow_entry.get("cost_tier") or "").strip().lower()
        if cost == "expensive":
            return {
                "cpu": "8+",
                "mem": "16G+",
                "est_runtime": workflow_entry.get("est_runtime") or "hours",
            }
        if cost:
            return {"est_runtime": workflow_entry.get("est_runtime") or cost}

    if spec is not None and str(spec.cost_hint or "").lower() == "expensive":
        return {"cpu": "4+", "mem": "8G+", "est_runtime": "minutes-to-hours"}
    return {}


def _infer_execution_story_kind(
    tool_id: str,
    *,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
    override: dict[str, Any],
) -> str:
    explicit = str(override.get("execution_story_kind") or "").strip()
    if explicit in EXECUTION_STORY_KINDS:
        return explicit

    lowered = str(tool_id or "").lower()
    if lowered in _HOSTED_TOOL_IDS:
        return "hosted_or_stateful_service"

    if isinstance(workflow_entry, dict):
        analysis = _workflow_recipe_analysis(workflow_entry)
        if analysis["python_safe"]:
            return "portable_python_compute"
        return "composite_workflow"

    runtime = infer_requires_runtime(
        spec.requires_runtime if spec is not None else None,
        backend=spec.backend if spec is not None else None,
    )
    if runtime == "network":
        return "hosted_or_stateful_service"
    if (
        runtime == "container"
        or any(lowered.startswith(prefix) for prefix in _NEURODESK_PREFIX_MAP)
        or _resolve_neurodesk_package_profile(tool_id)
    ):
        return "binary_backed_atomic"
    return "portable_python_compute"


def _default_execution_story(
    tool_id: str,
    *,
    execution_story_kind: str,
    supported_targets: list[str],
    override: dict[str, Any],
) -> dict[str, Any]:
    summary = str(override.get("execution_story_summary") or "").strip()
    next_steps = _normalize_list(override.get("execution_story_next_steps"))
    if summary:
        return {"summary": summary, "next_steps": next_steps}

    if execution_story_kind == "hosted_or_stateful_service":
        if str(tool_id or "").strip() == "kg_multihop_qa":
            return {
                "summary": (
                    "Run this tool through the deployed Brain Researcher MCP service "
                    "backed by BR-KG/Neo4j; no portable per-call local recipe is "
                    "advertised in v1."
                ),
                "next_steps": [
                    "Call the hosted Brain Researcher MCP tool directly.",
                    "Self-host BR-KG/Neo4j only if you need a private deployment.",
                ],
            }
        return {
            "summary": (
                "This tool is intended to run through the deployed Brain Researcher "
                "MCP service and does not advertise a portable per-call local recipe."
            ),
            "next_steps": [
                "Call the hosted Brain Researcher MCP tool directly.",
                "Self-host the backing service only if you need a private deployment.",
            ],
        }

    if execution_story_kind == "binary_backed_atomic":
        return {
            "summary": (
                "Requires runtime-specific binaries; use a Neurodesk, container, or "
                "cluster recipe instead of a bare Python recipe."
            ),
            "next_steps": [
                "Choose one of the advertised runtime targets.",
                "Install or mount the required binary environment before running.",
            ],
        }

    if execution_story_kind == "composite_workflow":
        target_text = (
            ", ".join(supported_targets) if supported_targets else "custom runtime"
        )
        return {
            "summary": (
                f"This workflow is a multi-step pipeline. Use the workflow-specific "
                f"recipe for {target_text} rather than assuming a generic bare-Python script."
            ),
            "next_steps": [
                "Pick a supported runtime target that matches your environment.",
                "Review the generated script before execution because intermediate files are workflow-specific.",
            ],
        }

    return {
        "summary": (
            "This tool can run in a local Python environment when its declared "
            "packages are installed."
        ),
        "next_steps": [
            "Create a local virtual environment.",
            "Install the declared Python packages.",
            "Run the generated script with your params.json.",
        ],
    }


def resolve_recipe_metadata(
    tool_id: str,
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lookup_tool_id = _recipe_lookup_tool_id(tool_id)
    override = get_tool_recipe_override(lookup_tool_id)
    workflow_inference_override = _workflow_inference_override(
        lookup_tool_id, workflow_entry
    )
    declared = _declared_recipe_metadata(
        lookup_tool_id, override=override, workflow_entry=workflow_entry
    )
    inferred_execution_story_kind = _infer_execution_story_kind(
        lookup_tool_id, spec=spec, workflow_entry=workflow_entry, override=override
    )
    if workflow_inference_override.get("execution_story_kind"):
        inferred_execution_story_kind = workflow_inference_override[
            "execution_story_kind"
        ]
    execution_story_kind = (
        declared["execution_story_kind"] or inferred_execution_story_kind
    )
    inferred_supported_targets = _infer_supported_targets(
        lookup_tool_id, spec=spec, workflow_entry=workflow_entry
    )
    if workflow_inference_override.get("supported_recipe_targets") is not None:
        inferred_supported_targets = list(
            workflow_inference_override["supported_recipe_targets"]
        )
    supported_targets = (
        list(declared["supported_recipe_targets"])
        if declared["supported_recipe_targets"] is not None
        else inferred_supported_targets
    )

    inferred_primary_target = normalize_recipe_target(
        inferred_supported_targets[0] if inferred_supported_targets else ""
    )
    if workflow_inference_override.get("primary_target") is not None:
        inferred_primary_target = workflow_inference_override["primary_target"]
    primary_target = normalize_recipe_target(
        declared["primary_target"]
        if declared["primary_target"] is not None
        else (supported_targets[0] if supported_targets else "")
    )
    if primary_target not in supported_targets and supported_targets:
        primary_target = supported_targets[0]

    recipe_family = declared["recipe_family"]
    python_packages = list(declared["python_packages"])
    if not python_packages:
        python_packages = _normalize_list(override.get("python_packages"))
    if not python_packages and "python" in supported_targets:
        python_packages = _direct_family_python_packages(recipe_family)
        if not python_packages:
            python_packages = _infer_python_packages(
                tool_id, spec=spec, workflow_entry=workflow_entry
            )

    required_env_vars = list(declared["required_env_vars"])
    if not required_env_vars:
        required_env_vars = _normalize_list(override.get("required_env_vars"))
    if not required_env_vars:
        required_env_vars = _infer_required_env_vars(
            tool_id, spec=spec, workflow_entry=workflow_entry
        )

    module_resolution = _neurodesk_module_resolution(tool_id)
    neurodesk_modules = _normalize_list(override.get("neurodesk_modules"))
    if not neurodesk_modules and any(
        target in supported_targets for target in ("neurodesk", "slurm")
    ):
        neurodesk_modules = _infer_neurodesk_modules(
            lookup_tool_id, workflow_entry=workflow_entry
        )

    container_images = _normalize_dict(override.get("container_images"))
    if not container_images:
        uses_bids_apps, apps = _workflow_uses_bids_apps(workflow_entry)
        if uses_bids_apps:
            for app in apps:
                image = get_container_image(app)
                if image:
                    container_images[app] = image

    recipe_depth = str(override.get("recipe_depth") or "").strip().lower()
    if recipe_depth not in {"summary", "runnable"}:
        recipe_depth = "runnable" if supported_targets else "summary"

    execution_story = _default_execution_story(
        lookup_tool_id,
        execution_story_kind=execution_story_kind,
        supported_targets=supported_targets,
        override=override,
    )
    hosted_via_br_mcp_service = _hosted_via_br_mcp_service(execution_story_kind)

    return {
        "known_recipe_subject": declared["has_declared_story_kind"]
        or declared["has_declared_supported_recipe_targets"]
        or declared["has_declared_primary_target"]
        or bool(override)
        or bool(module_resolution)
        or spec is not None
        or workflow_entry is not None,
        "canonical_tool_id": (
            resolve_primary_runtime_tool_id(
                str(spec.name).strip()
                if spec is not None and str(spec.name).strip()
                else lookup_tool_id
            )
            or (
                str(spec.name).strip()
                if spec is not None and str(spec.name).strip()
                else lookup_tool_id
            )
        ),
        "neurodesk_package_name": module_resolution.get("neurodesk_package_name"),
        "neurodesk_module_name": module_resolution.get("neurodesk_module_name"),
        "neurodesk_recommended_version": module_resolution.get(
            "neurodesk_recommended_version"
        ),
        "neurodesk_available_versions": module_resolution.get(
            "neurodesk_available_versions"
        )
        or [],
        "neurodesk_recommended_module": module_resolution.get(
            "neurodesk_recommended_module"
        ),
        "neurodesk_available_modules": module_resolution.get(
            "neurodesk_available_modules"
        )
        or [],
        "declared_execution_story_kind": declared["execution_story_kind"],
        "declared_supported_recipe_targets": (
            list(declared["supported_recipe_targets"])
            if declared["supported_recipe_targets"] is not None
            else None
        ),
        "declared_primary_target": normalize_recipe_target(
            declared["primary_target"] or ""
        ),
        "declared_recipe_family": declared["recipe_family"],
        "stable_workflow_pack": declared["stable_workflow_pack"],
        "source_repo": declared["source_repo"],
        "source_paper": declared["source_paper"],
        "tested_release": declared["tested_release"],
        "backend_options": declared["backend_options"],
        "example_dataset": declared["example_dataset"],
        "reference_assets": declared["reference_assets"],
        "artifact_contract": declared["artifact_contract"],
        "acceptance_gate": declared["acceptance_gate"],
        "runbook": declared["runbook"],
        "declared_recipe_sources": {
            "execution_story_kind": declared["story_source"],
            "supported_recipe_targets": declared["targets_source"],
            "primary_target": declared["primary_source"],
            "recipe_family": declared["family_source"],
        },
        "has_declared_recipe_metadata": declared["has_declared_recipe_metadata"],
        "has_declared_story_kind": declared["has_declared_story_kind"],
        "has_declared_supported_recipe_targets": declared[
            "has_declared_supported_recipe_targets"
        ],
        "has_declared_primary_target": declared["has_declared_primary_target"],
        "inferred_execution_story_kind": inferred_execution_story_kind,
        "inferred_supported_recipe_targets": inferred_supported_targets,
        "inferred_primary_target": inferred_primary_target,
        "execution_story_kind": execution_story_kind,
        "hosted_via_br_mcp_service": hosted_via_br_mcp_service,
        "execution_story": execution_story,
        "supported_recipe_targets": supported_targets,
        "primary_target": primary_target,
        "recipe_family": recipe_family,
        "recipe_depth": recipe_depth,
        "python_packages": python_packages,
        "required_env_vars": required_env_vars,
        "neurodesk_modules": neurodesk_modules,
        "container_images": container_images,
        "resource_profile": _infer_resource_profile(
            tool_id=lookup_tool_id,
            spec=spec,
            workflow_entry=workflow_entry,
            override=(
                {"resource_profile": declared["resource_profile"]}
                if declared["resource_profile"]
                else override
            ),
        ),
        "config_path": str(execution_recipe_config_path()),
    }


def recipe_card_metadata(
    tool_id: str,
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = resolve_recipe_metadata(
        tool_id, spec=spec, workflow_entry=workflow_entry
    )
    card = {
        "execution_recipe_available": bool(metadata["supported_recipe_targets"]),
        "execution_story_kind": metadata["execution_story_kind"],
        "hosted_via_br_mcp_service": metadata["hosted_via_br_mcp_service"],
        "execution_story": metadata["execution_story"],
        "supported_recipe_targets": metadata["supported_recipe_targets"],
        "recipe_depth": metadata["recipe_depth"],
        "primary_target": metadata["primary_target"],
        "canonical_tool_id": metadata.get("canonical_tool_id"),
        "neurodesk_package_name": metadata.get("neurodesk_package_name"),
        "neurodesk_module_name": metadata.get("neurodesk_module_name"),
        "neurodesk_recommended_version": metadata.get("neurodesk_recommended_version"),
        "neurodesk_recommended_module": metadata.get("neurodesk_recommended_module"),
        **agent_execution_metadata(
            metadata,
            recipe_available=bool(metadata["supported_recipe_targets"]),
        ),
    }
    if is_recipe_first_mcp_workflow(tool_id):
        card.update(
            {
                "recipe_first_workflow": True,
                "mcp_execution_posture": "recipe_first",
                "direct_tool_execution_supported": False,
                "manual_pipeline_execution_only": True,
                "recommended_mcp_entrypoint": "get_execution_recipe",
            }
        )
        if is_first_wave_heavy_runtime_workflow(tool_id):
            card.update(
                {
                    "heavy_runtime_workflow": True,
                    "workflow_surface_class": "heavy_runtime",
                    "execution_guidance": (
                        "Generate an execution recipe and run it via the advertised "
                        "external runtime; reserve pipeline_execute for manual/admin "
                        "approval paths."
                    ),
                }
            )
        elif is_long_running_batch_analysis_workflow(tool_id):
            card.update(
                {
                    "batch_analysis_workflow": True,
                    "workflow_surface_class": "batch_analysis",
                    "execution_guidance": (
                        "Generate a python execution recipe and run the generated "
                        "script/package outside the MCP server; reserve "
                        "pipeline_execute for manual/admin approval paths."
                    ),
                }
            )
    return card


def is_first_wave_heavy_runtime_workflow(tool_id: str) -> bool:
    return str(tool_id or "").strip() in _FIRST_WAVE_HEAVY_RUNTIME_WORKFLOWS


def is_long_running_batch_analysis_workflow(tool_id: str) -> bool:
    return str(tool_id or "").strip() in _LONG_RUNNING_BATCH_ANALYSIS_WORKFLOWS


def is_recipe_first_mcp_workflow(tool_id: str) -> bool:
    return is_first_wave_heavy_runtime_workflow(
        tool_id
    ) or is_long_running_batch_analysis_workflow(tool_id)


def agent_execution_metadata(
    metadata: dict[str, Any],
    *,
    requested_target: str | None = None,
    recipe_available: bool,
) -> dict[str, Any]:
    """Return agent-facing execution guidance derived from recipe metadata."""

    supported_targets = _normalize_list(metadata.get("supported_recipe_targets"))
    normalized_target = normalize_recipe_target(requested_target)
    artifact_contract = (
        metadata.get("artifact_contract")
        if isinstance(metadata.get("artifact_contract"), dict)
        else {}
    )
    expected_artifacts = _normalize_list(artifact_contract.get("required_outputs"))

    if metadata.get("hosted_via_br_mcp_service"):
        return {
            "agent_mode": "hosted_call",
            "supports_preview": False,
            "preview_kind": "none",
            "next_action": (
                "Call this capability through the deployed Brain Researcher MCP "
                "service instead of executing it locally."
            ),
            "expected_artifacts": expected_artifacts,
            "for_agents": True,
        }

    if supported_targets:
        if (
            normalized_target
            and normalized_target not in supported_targets
            and not recipe_available
        ):
            return {
                "agent_mode": "local_recipe",
                "supports_preview": True,
                "preview_kind": "synthetic",
                "next_action": (
                    f"Retry get_execution_recipe with one of the supported targets: "
                    f"{supported_targets}."
                ),
                "expected_artifacts": expected_artifacts,
                "for_agents": True,
            }
        return {
            "agent_mode": "local_recipe",
            "supports_preview": True,
            "preview_kind": "real",
            "next_action": (
                "Use the returned recipe files and run command in your local "
                "execution environment."
            ),
            "expected_artifacts": expected_artifacts,
            "for_agents": True,
        }

    return {
        "agent_mode": "manual_admin_only",
        "supports_preview": False,
        "preview_kind": "none",
        "next_action": (
            "Treat this as a manual/admin path only. Do not assume MCP provides a "
            "portable local recipe for agents."
        ),
        "expected_artifacts": expected_artifacts,
        "for_agents": False,
    }


def _default_runtime_script(tool_id: str) -> str:
    return (
        "import json\n"
        "from pathlib import Path\n\n"
        "from brain_researcher.services.tools.executor import execute_tool\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        f'result = execute_tool("{tool_id}", params)\n'
        'print(json.dumps(result.model_dump(mode="python"), indent=2, sort_keys=True, default=str))\n'
    )


def _glm_first_level_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from nilearn.glm.first_level import FirstLevelModel
        from nilearn.image import load_img


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        img_path = Path(params["img"]).expanduser().resolve()
        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "glm_first_level")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        img = load_img(str(img_path))
        t_r = params.get("t_r")
        if t_r is None:
            zooms = img.header.get_zooms()
            t_r = float(zooms[3]) if len(zooms) >= 4 else 2.0

        events_path = params.get("events")
        if events_path:
            events_file = Path(events_path).expanduser().resolve()
            sep = "\\t" if events_file.suffix.lower() == ".tsv" else ","
            events = pd.read_csv(events_file, sep=sep)
        else:
            n_scans = int(img.shape[3])
            events = pd.DataFrame(
                {
                    "onset": [0.0],
                    "duration": [float(n_scans) * float(t_r)],
                    "trial_type": ["stim"],
                }
            )

        model = FirstLevelModel(
            t_r=float(t_r),
            hrf_model=str(params.get("hrf_model", "spm")),
            drift_model=str(params.get("drift_model", "cosine")),
            high_pass=float(params.get("high_pass", 0.01)),
            mask_img=params.get("mask_img"),
            smoothing_fwhm=params.get("smoothing_fwhm"),
            standardize=bool(params.get("standardize", True)),
            noise_model=str(params.get("noise_model", "ar1")),
            n_jobs=int(params.get("n_jobs", -1)),
        ).fit(str(img_path), events)

        design_matrix = model.design_matrices_[0]
        contrasts = params.get("contrasts") or {}
        if not contrasts:
            usable_columns = [
                column
                for column in design_matrix.columns
                if column.lower() not in {"constant", "intercept"}
            ]
            for column in usable_columns:
                vector = np.zeros(len(design_matrix.columns), dtype=float)
                vector[design_matrix.columns.get_loc(column)] = 1.0
                contrasts[column] = vector.tolist()

        zmaps = []
        for name, contrast in contrasts.items():
            contrast_def = (
                np.asarray(contrast, dtype=float)
                if isinstance(contrast, (list, tuple))
                else contrast
            )
            z_map = model.compute_contrast(contrast_def, output_type="z_score")
            zmap_path = output_dir / f"{name}_zmap.nii.gz"
            z_map.to_filename(zmap_path)
            zmaps.append(str(zmap_path))

        summary = {
            "hrf_model": str(params.get("hrf_model", "spm")),
            "noise_model": str(params.get("noise_model", "ar1")),
            "contrasts": list(contrasts.keys()),
            "design_columns": list(design_matrix.columns),
            "n_scans": int(design_matrix.shape[0]),
            "used_nilearn_package": True,
        }
        summary_path = output_dir / "glm_first_level_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(
            json.dumps(
                {
                    "outputs": {
                        "summary": str(summary_path),
                        "zmaps": zmaps,
                    },
                    "summary": summary,
                    "message": "First-level GLM completed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _glm_second_level_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from nilearn.glm.second_level import SecondLevelModel


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        contrast_maps = [
            str(Path(path).expanduser().resolve())
            for path in params.get("contrast_maps", [])
        ]
        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "glm_second_level")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        design_matrix_payload = params.get("design_matrix")
        if isinstance(design_matrix_payload, str):
            design_matrix_path = Path(design_matrix_payload).expanduser().resolve()
            sep = "\\t" if design_matrix_path.suffix.lower() == ".tsv" else ","
            design_matrix = pd.read_csv(design_matrix_path, sep=sep)
        elif isinstance(design_matrix_payload, dict):
            design_matrix = pd.DataFrame(design_matrix_payload)
        else:
            design_matrix = pd.DataFrame({"intercept": np.ones(len(contrast_maps))})

        model_kwargs = {
            "mask_img": params.get("mask_img"),
            "smoothing_fwhm": params.get("smoothing_fwhm"),
        }
        model_type = str(params.get("model_type", "ols"))
        try:
            model = SecondLevelModel(
                model_type=model_type,
                **model_kwargs,
            ).fit(contrast_maps, design_matrix=design_matrix)
        except TypeError:
            model = SecondLevelModel(**model_kwargs).fit(
                contrast_maps,
                design_matrix=design_matrix,
            )

        contrast = params.get("contrast") or "intercept"
        z_map = model.compute_contrast(contrast, output_type="z_score")
        zmap_path = output_dir / "group_zmap.nii.gz"
        z_map.to_filename(zmap_path)

        summary = {
            "model_type": model_type,
            "n_maps": len(contrast_maps),
            "design_columns": list(design_matrix.columns),
            "used_nilearn_package": True,
        }
        summary_path = output_dir / "glm_second_level_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(
            json.dumps(
                {
                    "outputs": {
                        "summary": str(summary_path),
                        "zmap": str(zmap_path),
                    },
                    "summary": summary,
                    "message": "Second-level GLM completed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _connectivity_matrix_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np
        from nilearn.connectome import ConnectivityMeasure

        from brain_researcher.core.analysis.connectivity_contracts import (
            build_feature_contract,
            safe_fisher_z,
            write_feature_contract,
        )


        def _load_timeseries(value):
            if isinstance(value, str):
                path = Path(value).expanduser().resolve()
                suffix = path.suffix.lower()
                if suffix in {".npy", ".npz"}:
                    data = np.load(path)
                elif suffix in {".csv", ".tsv", ".txt"}:
                    delimiter = "," if suffix == ".csv" else "\\t"
                    data = np.loadtxt(path, delimiter=delimiter)
                else:
                    data = np.load(path)
            elif isinstance(value, list) and value and isinstance(value[0], str):
                loaded = []
                for item in value:
                    path = Path(item).expanduser().resolve()
                    suffix = path.suffix.lower()
                    if suffix in {".npy", ".npz"}:
                        loaded.append(np.load(path))
                    elif suffix in {".csv", ".tsv", ".txt"}:
                        delimiter = "," if suffix == ".csv" else "\\t"
                        loaded.append(np.loadtxt(path, delimiter=delimiter))
                    else:
                        loaded.append(np.load(path))
                data = np.asarray(loaded)
            else:
                data = np.asarray(value, dtype=float)

            if data.ndim == 1:
                raise ValueError("timeseries input must be at least 2D (time x roi)")
            if data.ndim == 2:
                data = data[np.newaxis, ...]
            if data.ndim != 3:
                raise ValueError(
                    f"timeseries array must be 3D (subjects x time x roi), got {data.ndim}"
                )
            return np.asarray(data, dtype=float)


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        timeseries = _load_timeseries(params["timeseries"])
        measure = ConnectivityMeasure(
            kind=str(params.get("kind", "correlation")),
            vectorize=bool(params.get("vectorize", False)),
            discard_diagonal=bool(params.get("discard_diagonal", False)),
            standardize="zscore_sample",
        )
        matrix = measure.fit_transform([timeseries[idx] for idx in range(timeseries.shape[0])])
        fisher_z_diagnostics = None
        if bool(params.get("fisher_z", True)):
            matrix, fisher_z_diagnostics = safe_fisher_z(
                matrix,
                f"connectivity_matrix(kind={params.get('kind', 'correlation')})",
                return_diagnostics=True,
            )

        output_file = Path(
            params.get("output_file") or (Path.cwd() / "connectivity_matrix.npy")
        ).expanduser().resolve()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_file, matrix)

        summary = {
            "kind": str(params.get("kind", "correlation")),
            "shape": list(matrix.shape),
            "n_subjects": int(timeseries.shape[0]),
            "n_rois": int(timeseries.shape[-1]),
            "used_nilearn_package": True,
            "fisher_z_applied": bool(params.get("fisher_z", True)),
        }
        if fisher_z_diagnostics is not None:
            summary["fisher_z_diagnostics"] = fisher_z_diagnostics
        outputs = {
            "matrix": str(output_file),
            "connectivity_matrix": str(output_file),
        }
        try:
            cov_estimator_obj = getattr(measure, "cov_estimator_", None) or getattr(
                measure, "cov_estimator", None
            )
            cov_estimator_name = (
                type(cov_estimator_obj).__name__
                if cov_estimator_obj is not None
                else None
            )
            contract = build_feature_contract(
                matrix,
                matrix_kind=str(params.get("kind", "correlation")),
                source_level="roi_timeseries",
                n_rois=int(timeseries.shape[-1]),
                n_timepoints=int(timeseries.shape[1]),
                effective_n_timepoints=int(timeseries.shape[1]),
                covariance_estimator=cov_estimator_name,
                fisher_z_diagnostics=fisher_z_diagnostics,
                extras={
                    "n_subjects": int(timeseries.shape[0]),
                    "vectorize": bool(params.get("vectorize", False)),
                    "discard_diagonal": bool(params.get("discard_diagonal", False)),
                },
            )
            outputs["feature_contract"] = str(
                write_feature_contract(contract, output_file.parent)
            )
        except Exception as exc:
            summary["feature_contract_warning"] = (
                f"feature_contract sidecar emission failed: {exc!r}"
            )
        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "message": "Connectivity matrix computed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _seed_based_connectivity_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from nilearn.maskers import NiftiMasker, NiftiSpheresMasker


        def _zscore(values, axis):
            mean = values.mean(axis=axis, keepdims=True)
            std = values.std(axis=axis, keepdims=True)
            std[std < 1e-6] = 1e-6
            return (values - mean) / std


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        img_path = Path(params["img"]).expanduser().resolve()
        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "seed_based_fc")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        confounds = None
        confounds_path = params.get("confounds")
        if confounds_path:
            confounds_file = Path(confounds_path).expanduser().resolve()
            sep = "\\t" if confounds_file.suffix.lower() == ".tsv" else ","
            confounds = (
                pd.read_csv(confounds_file, sep=sep)
                .select_dtypes(include=[np.number])
                .fillna(0.0)
                .to_numpy()
            )
            confound_mean = confounds.mean(axis=0, keepdims=True)
            confound_std = confounds.std(axis=0, ddof=1, keepdims=True)
            confound_std[~np.isfinite(confound_std) | (confound_std < 1e-6)] = 1.0
            confounds = (confounds - confound_mean) / confound_std

        brain_masker = NiftiMasker(
            mask_img=params.get("mask_img"),
            smoothing_fwhm=params.get("smoothing_fwhm"),
            standardize=(
                "zscore_sample" if bool(params.get("standardize", True)) else False
            ),
            standardize_confounds=False,
            detrend=bool(params.get("detrend", True)),
            low_pass=params.get("low_pass"),
            high_pass=params.get("high_pass"),
            t_r=params.get("t_r"),
        )
        brain_ts = brain_masker.fit_transform(str(img_path), confounds=confounds)

        seed_mask = params.get("seed_mask")
        if seed_mask:
            seed_masker = NiftiMasker(
                mask_img=str(Path(seed_mask).expanduser().resolve()),
                standardize=(
                    "zscore_sample" if bool(params.get("standardize", True)) else False
                ),
                standardize_confounds=False,
                detrend=bool(params.get("detrend", True)),
                low_pass=params.get("low_pass"),
                high_pass=params.get("high_pass"),
                t_r=params.get("t_r"),
            )
            seed_ts = seed_masker.fit_transform(str(img_path), confounds=confounds)
            seed_descriptor = seed_mask
        else:
            seed_coords = params.get("seed_coords")
            if not seed_coords:
                raise ValueError("seed_coords or seed_mask is required")
            seed_masker = NiftiSpheresMasker(
                [tuple(seed_coords)],
                radius=float(params.get("radius", 8.0)),
                standardize=(
                    "zscore_sample" if bool(params.get("standardize", True)) else False
                ),
                standardize_confounds=False,
                detrend=bool(params.get("detrend", True)),
                low_pass=params.get("low_pass"),
                high_pass=params.get("high_pass"),
                t_r=params.get("t_r"),
            )
            seed_ts = seed_masker.fit_transform(str(img_path), confounds=confounds)
            seed_descriptor = seed_coords

        seed_ts = _zscore(seed_ts.mean(axis=1, keepdims=True), axis=0)
        brain_ts = _zscore(brain_ts, axis=0)
        corr = (brain_ts * seed_ts).mean(axis=0)
        seed_map = brain_masker.inverse_transform(corr)

        output_file = Path(
            params.get("output_file")
            or (output_dir / "seed_based_connectivity.nii.gz")
        ).expanduser().resolve()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        seed_map.to_filename(output_file)

        summary = {
            "radius": float(params.get("radius", 8.0)),
            "seed": seed_descriptor,
            "n_voxels": int(corr.size),
            "used_nilearn_package": True,
        }
        print(
            json.dumps(
                {
                    "outputs": {"map": str(output_file)},
                    "summary": summary,
                    "message": "Seed-based connectivity completed.",
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        """).lstrip()


def _mvpa_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        from sklearn.feature_selection import SelectKBest, f_classif
        from sklearn.linear_model import LogisticRegression, RidgeClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.naive_bayes import GaussianNB
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import LinearSVC


        def _load_labels(value):
            if isinstance(value, str):
                path = Path(value).expanduser().resolve()
                if path.suffix.lower() == ".npy":
                    labels = np.load(path)
                else:
                    delimiter = "," if path.suffix.lower() == ".csv" else None
                    labels = np.loadtxt(path, delimiter=delimiter)
                return np.asarray(labels).ravel()
            return np.asarray(value).ravel()


        def _load_data(path_text, *, mask_img=None, standardize=False, smoothing_fwhm=None):
            path = Path(path_text).expanduser().resolve()
            lower_name = path.name.lower()
            if lower_name.endswith(".nii") or lower_name.endswith(".nii.gz"):
                from nilearn.maskers import NiftiMasker

                masker = NiftiMasker(
                    mask_img=(
                        str(Path(mask_img).expanduser().resolve()) if mask_img else None
                    ),
                    standardize=standardize,
                    smoothing_fwhm=smoothing_fwhm,
                )
                data = masker.fit_transform(str(path))
            elif path.suffix.lower() == ".npy":
                data = np.load(path)
            else:
                delimiter = "," if path.suffix.lower() == ".csv" else None
                data = np.loadtxt(path, delimiter=delimiter)
            if data.ndim == 1:
                data = data[:, np.newaxis]
            return np.asarray(data, dtype=float)


        def _build_classifier(name, seed):
            lowered = str(name or "svc").lower()
            if lowered in {"lda", "linear_discriminant_analysis"}:
                return LinearDiscriminantAnalysis()
            if lowered in {"gnb", "gaussiannb"}:
                return GaussianNB()
            if lowered in {"ridge", "ridge_classifier"}:
                return RidgeClassifier()
            if lowered in {"logistic", "logreg", "logistic_regression"}:
                return LogisticRegression(
                    max_iter=1000,
                    random_state=seed,
                    solver="liblinear",
                )
            return LinearSVC(random_state=seed, dual="auto")


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        data = _load_data(
            params["img"],
            mask_img=params.get("mask_img"),
            standardize=False,
            smoothing_fwhm=params.get("smoothing_fwhm"),
        )
        labels = _load_labels(params["labels"])
        if len(labels) != data.shape[0]:
            raise ValueError("labels length must match number of samples in img")

        steps = []
        if bool(params.get("standardize", True)):
            steps.append(("scale", StandardScaler()))
        k_features = params.get("n_features")
        if params.get("feature_selection") and k_features:
            steps.append(
                ("select", SelectKBest(score_func=f_classif, k=min(int(k_features), data.shape[1])))
            )
        steps.append(
            (
                "classifier",
                _build_classifier(params.get("classifier", "svc"), params.get("seed")),
            )
        )
        pipeline = Pipeline(steps)

        cv_folds = int(params.get("cv_folds", 5))
        splitter = StratifiedKFold(
            n_splits=max(2, min(cv_folds, len(labels))),
            shuffle=True,
            random_state=params.get("seed"),
        )
        scores = cross_val_score(pipeline, data, labels, cv=splitter, scoring="accuracy")

        pvalue = None
        permutations = int(params.get("permutations", 0))
        if permutations > 0:
            rng = np.random.default_rng(params.get("seed"))
            null_scores = []
            for _ in range(permutations):
                shuffled = rng.permutation(labels)
                null_scores.append(
                    float(
                        np.mean(
                            cross_val_score(
                                pipeline,
                                data,
                                shuffled,
                                cv=splitter,
                                scoring="accuracy",
                            )
                        )
                    )
                )
            pvalue = float(
                (np.sum(np.asarray(null_scores) >= float(scores.mean())) + 1)
                / (len(null_scores) + 1)
            )

        summary = {
            "classifier": str(params.get("classifier", "svc")),
            "accuracy": float(scores.mean()),
            "std": float(scores.std(ddof=0)),
            "folds": int(len(scores)),
            "used_sklearn": True,
        }
        outputs = {"summary": None, "scores": None}
        output_dir = params.get("output_dir")
        if output_dir:
            out_dir = Path(output_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            scores_path = out_dir / "mvpa_scores.npy"
            np.save(scores_path, scores)
            outputs["scores"] = str(scores_path)
            summary_path = out_dir / "mvpa_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            outputs["summary"] = str(summary_path)

        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "scores": scores.tolist(),
                    "pvalue": pvalue,
                    "message": "MVPA decoding completed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _temporal_decoding_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np


        def _load_array(path_text):
            path = Path(path_text).expanduser().resolve()
            if path.suffix.lower() == ".npy":
                return np.load(path)
            if path.suffix.lower() == ".npz":
                archive = np.load(path)
                return archive[archive.files[0]]
            raise ValueError(f"unsupported array format: {path_text}")


        def _standardize(values):
            mean = np.mean(values, axis=0, keepdims=True)
            std = np.std(values, axis=0, keepdims=True) + 1e-6
            return (values - mean) / std


        def _generate_windows(length, window_size, step):
            windows = []
            for start in range(0, length - window_size + 1, step):
                windows.append((start, start + window_size))
            return windows or [(0, length)]


        def _compute_cv_folds(labels, requested_folds):
            _, counts = np.unique(labels, return_counts=True)
            if counts.size < 2:
                return 0
            max_folds = int(min(max(2, requested_folds), np.min(counts)))
            return max_folds if max_folds >= 2 else 0


        def _nearest_centroid_predict(train_x, train_y, test_x):
            classes = np.unique(train_y)
            centroids = np.vstack([train_x[train_y == cls].mean(axis=0) for cls in classes])
            dists = np.sum((test_x[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
            return classes[np.argmin(dists, axis=1)]


        def _deterministic_stratified_folds(labels, n_splits):
            folds = [[] for _ in range(n_splits)]
            for cls in np.unique(labels):
                cls_idx = np.where(labels == cls)[0]
                for index, row_id in enumerate(cls_idx):
                    folds[index % n_splits].append(int(row_id))
            return [np.asarray(sorted(fold), dtype=int) for fold in folds if fold]


        def _nearest_centroid_cv_accuracy(data, labels, n_splits):
            all_idx = np.arange(labels.size)
            fold_accuracies = []
            for test_idx in _deterministic_stratified_folds(labels, n_splits):
                train_idx = np.setdiff1d(all_idx, test_idx)
                train_labels = labels[train_idx]
                if np.unique(train_labels).size < 2:
                    continue
                predictions = _nearest_centroid_predict(
                    data[train_idx],
                    train_labels,
                    data[test_idx],
                )
                fold_accuracies.append(float(np.mean(predictions == labels[test_idx])))
            if not fold_accuracies:
                _, counts = np.unique(labels, return_counts=True)
                return float(np.max(counts) / labels.size)
            return float(np.mean(fold_accuracies))


        def _run_sklearn_cv(data, labels, classifier_name, n_splits, random_state):
            from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
            from sklearn.linear_model import LogisticRegression, RidgeClassifier
            from sklearn.model_selection import StratifiedKFold, cross_val_score
            from sklearn.svm import LinearSVC

            lowered = str(classifier_name or "lda").lower()
            if lowered == "lda":
                classifier = LinearDiscriminantAnalysis()
            elif lowered in {"svm", "svc", "linearsvc"}:
                classifier = LinearSVC(random_state=random_state)
            elif lowered in {"ridge", "ridge_classifier"}:
                classifier = RidgeClassifier()
            else:
                classifier = LogisticRegression(
                    max_iter=1000,
                    random_state=random_state,
                    solver="liblinear",
                )

            cv = StratifiedKFold(
                n_splits=n_splits,
                shuffle=True,
                random_state=0 if random_state is None else int(random_state),
            )
            scores = cross_val_score(classifier, data, labels, cv=cv, scoring="accuracy")
            return float(np.mean(scores)), "sklearn_cv"


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        data = _load_array(params["data_file"])
        labels = np.asarray(_load_array(params["labels_file"])).astype(int).reshape(-1)

        if data.ndim == 3:
            timepoints = data.shape[0]
            timeseries = np.transpose(data, (2, 0, 1))
        elif data.ndim == 2:
            if labels.size == data.shape[0] and labels.size >= 2:
                timepoints = 1
                timeseries = data[:, np.newaxis, :]
            else:
                timepoints = data.shape[0]
                timeseries = data[np.newaxis, ...]
        else:
            raise ValueError("data must be 2D or 3D")

        n_trials = timeseries.shape[0]
        if labels.size < n_trials:
            raise ValueError("labels must contain at least one label per trial")
        labels = labels[:n_trials]

        window_size = int(params.get("window_size") or max(1, timepoints // 10))
        window_step = int(params.get("window_step", 1))
        windows = _generate_windows(timepoints, window_size, window_step)

        accuracies = []
        patterns = []
        backend_names = []
        backend_reasons = []
        for start, end in windows:
            window_data = timeseries[:, start:end, :].reshape(n_trials, -1)
            window_data = _standardize(window_data)
            n_splits = _compute_cv_folds(labels, int(params.get("cv_folds", 5)))
            if labels.size < 2 or np.unique(labels).size < 2:
                accuracy = 0.0
                backend_name = "insufficient_labels"
                backend_reason = "single_class_or_not_enough_trials"
            elif n_splits < 2:
                _, counts = np.unique(labels, return_counts=True)
                accuracy = float(np.max(counts) / labels.size)
                backend_name = "insufficient_cv_folds"
                backend_reason = "class_counts_too_small_for_cv"
            else:
                try:
                    accuracy, backend_name = _run_sklearn_cv(
                        window_data,
                        labels,
                        params.get("classifier", "lda"),
                        n_splits,
                        params.get("random_state"),
                    )
                    backend_reason = "ok"
                except Exception:
                    accuracy = _nearest_centroid_cv_accuracy(window_data, labels, n_splits)
                    backend_name = "numpy_nearest_centroid_cv"
                    backend_reason = "sklearn_failed_or_unavailable"
            accuracies.append(float(accuracy))
            backend_names.append(backend_name)
            backend_reasons.append(backend_reason)
            patterns.append(window_data.mean(axis=0))

        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "temporal_decoding")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        mean_accuracy = float(np.mean(accuracies))
        std_accuracy = float(np.std(accuracies))
        summary = {
            "method": str(params.get("method", "sliding_window")),
            "classifier": str(params.get("classifier", "lda")),
            "n_trials": int(n_trials),
            "window_size": int(window_size),
            "n_windows": int(len(windows)),
            "mean_accuracy": mean_accuracy,
            "std_accuracy": std_accuracy,
            "n_classes": int(np.unique(labels).size),
            "effective_cv_folds": int(_compute_cv_folds(labels, int(params.get("cv_folds", 5)))),
            "used_full_backend": any(name == "sklearn_cv" for name in backend_names),
            "backend_name": (
                backend_names[0] if len(set(backend_names)) == 1 else "mixed_backends"
            ),
            "backend_reason": (
                backend_reasons[0]
                if len(set(backend_reasons)) == 1
                else "mixed_reasons"
            ),
        }

        outputs = {"summary": None, "accuracies": None, "patterns": None}
        summary_path = output_dir / "temporal_decoding_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        outputs["summary"] = str(summary_path)

        if bool(params.get("save_accuracies", True)):
            acc_path = output_dir / "temporal_accuracies.npy"
            np.save(acc_path, np.asarray(accuracies))
            outputs["accuracies"] = str(acc_path)

        if bool(params.get("save_patterns", True)):
            patterns_path = output_dir / "temporal_patterns.npy"
            np.save(patterns_path, np.asarray(patterns))
            outputs["patterns"] = str(patterns_path)

        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "accuracies": accuracies,
                    "message": f"Temporal decoding completed ({summary['backend_name']}).",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _encoding_models_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np


        def _load_array(path_text):
            path = Path(path_text).expanduser().resolve()
            if path.suffix.lower() == ".npy":
                return np.load(path)
            if path.suffix.lower() == ".npz":
                archive = np.load(path)
                return archive[archive.files[0]]
            raise ValueError(f"unsupported array format: {path_text}")


        def _prepare_design_matrix(stimulus, add_derivatives):
            design = stimulus
            if add_derivatives:
                first_derivative = np.diff(stimulus, axis=0, prepend=stimulus[0:1])
                design = np.concatenate([design, first_derivative], axis=1)
            return design


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        brain_data = _load_array(params["brain_data_file"])
        stimulus = _load_array(params["stimulus_file"])
        if brain_data.shape[0] != stimulus.shape[0]:
            raise ValueError("brain data and stimulus must share the same time dimension")

        design = _prepare_design_matrix(stimulus, bool(params.get("add_derivatives", False)))
        if bool(params.get("standardize", True)):
            design = (design - np.mean(design, axis=0)) / (np.std(design, axis=0) + 1e-6)

        alpha = 1.0
        xtx = design.T @ design
        ridge_matrix = xtx + alpha * np.eye(xtx.shape[0])
        xty = design.T @ brain_data
        try:
            weights = np.linalg.solve(ridge_matrix, xty)
            used_full_backend = bool(np.all(np.isfinite(weights)))
            backend_name = "numpy_solve"
        except np.linalg.LinAlgError:
            weights = np.linalg.pinv(ridge_matrix) @ xty
            used_full_backend = False
            backend_name = "numpy_fallback"

        predicted = design @ weights
        residuals = brain_data - predicted
        denom = np.sum(
            (brain_data - np.mean(brain_data, axis=0)) ** 2,
            axis=0,
        ) + 1e-8
        r2_scores = 1.0 - np.sum(residuals ** 2, axis=0) / denom
        r2_scores = np.clip(r2_scores, -1.0, 1.0)

        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "encoding_models")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        outputs = {"summary": None, "weights": None, "predictions": None, "model": None}
        if bool(params.get("save_weights", True)):
            weights_path = output_dir / "encoding_weights.npy"
            np.save(weights_path, weights)
            outputs["weights"] = str(weights_path)
        if bool(params.get("save_predictions", True)):
            predictions_path = output_dir / "encoding_predictions.npy"
            np.save(predictions_path, predicted)
            outputs["predictions"] = str(predictions_path)

        summary = {
            "model_type": str(params.get("model_type", "ridge")).lower(),
            "n_timepoints": int(brain_data.shape[0]),
            "n_voxels": int(brain_data.shape[1]),
            "n_features": int(design.shape[1]),
            "mean_r2": float(np.mean(r2_scores)),
            "median_r2": float(np.median(r2_scores)),
            "used_full_backend": used_full_backend,
            "backend_name": backend_name,
        }
        summary_path = output_dir / "encoding_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        outputs["summary"] = str(summary_path)

        if bool(params.get("save_models", True)):
            model_path = output_dir / "encoding_model.json"
            model_path.write_text(
                json.dumps({"alpha": alpha, "type": summary["model_type"]}),
                encoding="utf-8",
            )
            outputs["model"] = str(model_path)

        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "r2_scores": r2_scores.tolist(),
                    "message": f"Encoding model completed ({backend_name}).",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _searchlight_python_script() -> str:
    return dedent("""
        import json
        from pathlib import Path

        import numpy as np
        from nilearn import image
        from nilearn.searchlight import SearchLight


        def _load_labels(params):
            labels = params.get("labels")
            if labels is not None:
                return np.asarray(labels)
            labels_file = params.get("labels_file")
            if labels_file:
                return np.loadtxt(Path(labels_file).expanduser().resolve())
            raise ValueError("labels or labels_file is required for searchlight analysis")


        def _get_classifier(name, analysis_type):
            from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
            from sklearn.linear_model import LogisticRegression, Ridge, RidgeClassifier
            from sklearn.naive_bayes import GaussianNB
            from sklearn.svm import SVC, SVR

            lowered = str(name or "svm").lower()
            if analysis_type == "regression":
                if lowered == "svr":
                    return SVR(kernel="linear", C=1.0)
                return Ridge()
            classifiers = {
                "svm": SVC(kernel="linear", C=1.0),
                "svc": SVC(kernel="linear", C=1.0),
                "lda": LinearDiscriminantAnalysis(),
                "gnb": GaussianNB(),
                "ridge": RidgeClassifier(),
                "logistic": LogisticRegression(max_iter=1000),
            }
            return classifiers.get(lowered, SVC(kernel="linear", C=1.0))


        def _searchlight_classification(func_img, labels, radius, classifier_name, cv_folds, n_jobs, mask_img):
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=_get_classifier(classifier_name, "classification"),
                cv=cv_folds,
                scoring="accuracy",
            )
            searchlight.fit(func_img, labels)
            return searchlight.scores_img_


        def _searchlight_regression(func_img, targets, radius, regressor_name, cv_folds, n_jobs, mask_img):
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=_get_classifier(regressor_name, "regression"),
                cv=cv_folds,
                scoring="r2",
            )
            searchlight.fit(func_img, targets)
            return searchlight.scores_img_


        def _searchlight_rsa(func_img, model_rdm, radius, n_jobs, mask_img):
            from scipy.stats import spearmanr
            from sklearn.base import BaseEstimator


            class RSAEstimator(BaseEstimator):
                def __init__(self, model_rdm):
                    self.model_rdm = model_rdm

                def fit(self, X, y=None):
                    data_rdm = 1 - np.corrcoef(X)
                    upper = np.triu_indices(data_rdm.shape[0], k=1)
                    corr, _ = spearmanr(data_rdm[upper], self.model_rdm[upper])
                    self.score_ = 0.0 if np.isnan(corr) else float(corr)
                    return self

                def score(self, X, y=None):
                    return self.score_


            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=RSAEstimator(model_rdm),
            )
            searchlight.fit(func_img)
            return searchlight.scores_img_


        def _permutation_searchlight(func_img, labels, radius, classifier_name, cv_folds, n_permutations, n_jobs, mask_img):
            observed_img = _searchlight_classification(
                func_img,
                labels,
                radius,
                classifier_name,
                cv_folds,
                n_jobs,
                mask_img,
            )
            perm_scores = []
            rng = np.random.default_rng(0)
            for _ in range(n_permutations):
                perm_img = _searchlight_classification(
                    func_img,
                    rng.permutation(labels),
                    radius,
                    classifier_name,
                    cv_folds,
                    n_jobs,
                    mask_img,
                )
                perm_scores.append(perm_img.get_fdata())
            p_values = np.mean(
                np.asarray(perm_scores) >= observed_img.get_fdata()[np.newaxis, ...],
                axis=0,
            )
            return observed_img, image.new_img_like(observed_img, p_values)


        def _plot(scores_img, output_file, threshold, title):
            from nilearn import plotting
            import matplotlib.pyplot as plt

            figure = plt.figure(figsize=(12, 8))
            plotting.plot_glass_brain(
                scores_img,
                threshold=threshold,
                colorbar=True,
                title=title,
                figure=figure,
            )
            plt.savefig(output_file, dpi=150, bbox_inches="tight")
            plt.close()


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        func_img = image.load_img(str(Path(params["func_file"]).expanduser().resolve()))
        mask_file = params.get("mask_file")
        mask_img = image.load_img(str(Path(mask_file).expanduser().resolve())) if mask_file else None
        labels = _load_labels(params)
        output_dir = Path(params["output_dir"]).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        analysis_type = str(params.get("analysis_type", "classification"))
        radius = float(params.get("radius", 6.0))
        classifier = str(params.get("classifier", "svm"))
        cv_folds = int(params.get("cv_folds", 5))
        n_jobs = int(params.get("n_jobs", 1))
        n_permutations = int(params.get("n_permutations", 0))

        if analysis_type == "classification":
            if n_permutations > 0:
                scores_img, p_value_img = _permutation_searchlight(
                    func_img,
                    labels,
                    radius,
                    classifier,
                    cv_folds,
                    n_permutations,
                    n_jobs,
                    mask_img,
                )
            else:
                scores_img = _searchlight_classification(
                    func_img,
                    labels,
                    radius,
                    classifier,
                    cv_folds,
                    n_jobs,
                    mask_img,
                )
                p_value_img = None
        elif analysis_type == "regression":
            scores_img = _searchlight_regression(
                func_img,
                labels,
                radius,
                classifier,
                cv_folds,
                n_jobs,
                mask_img,
            )
            p_value_img = None
        elif analysis_type == "rsa":
            model_rdm_file = params.get("model_rdm_file")
            if not model_rdm_file:
                raise ValueError("model_rdm_file is required for RSA searchlight")
            model_rdm = np.load(Path(model_rdm_file).expanduser().resolve())
            scores_img = _searchlight_rsa(
                func_img,
                model_rdm,
                radius,
                n_jobs,
                mask_img,
            )
            p_value_img = None
        else:
            raise ValueError(f"unknown analysis_type: {analysis_type}")

        output_files = {}
        if bool(params.get("save_maps", True)):
            scores_file = output_dir / f"searchlight_{analysis_type}_scores.nii.gz"
            scores_img.to_filename(scores_file)
            output_files["scores_map"] = str(scores_file)
            if p_value_img is not None:
                p_file = output_dir / f"searchlight_{analysis_type}_pvalues.nii.gz"
                p_value_img.to_filename(p_file)
                output_files["p_value_map"] = str(p_file)

        scores_data = scores_img.get_fdata()
        valid_scores = scores_data[~np.isnan(scores_data) & (scores_data != 0)]
        stats = {
            "mean_score": float(np.mean(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "std_score": float(np.std(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "max_score": float(np.max(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "min_score": float(np.min(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "n_voxels_analyzed": int(len(valid_scores)),
            "parameters": {
                "radius": radius,
                "analysis_type": analysis_type,
                "classifier": classifier if analysis_type == "classification" else None,
                "cv_folds": cv_folds,
                "n_permutations": n_permutations,
            },
        }

        if bool(params.get("plot_results", True)):
            threshold = params.get("threshold")
            plot_file = output_dir / f"searchlight_{analysis_type}_plot.png"
            _plot(scores_img, str(plot_file), threshold, f"Searchlight {analysis_type.title()} Results")
            output_files["plot"] = str(plot_file)
            if p_value_img is not None:
                p_plot_file = output_dir / f"searchlight_{analysis_type}_pvalue_plot.png"
                _plot(p_value_img, str(p_plot_file), 0.05, "Searchlight P-values")
                output_files["p_value_plot"] = str(p_plot_file)

        if bool(params.get("save_stats", True)):
            stats_file = output_dir / f"searchlight_{analysis_type}_stats.json"
            stats_file.write_text(json.dumps(stats, indent=2), encoding="utf-8")
            output_files["stats"] = str(stats_file)

        print(
            json.dumps(
                {
                    "outputs": output_files,
                    "statistics": stats,
                    "message": f"Searchlight {analysis_type} completed: mean score = {stats['mean_score']:.3f}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """).lstrip()


def _direct_python_script_for_family(tool_id: str, recipe_family: str) -> str:
    if recipe_family == "glm":
        return (
            _glm_first_level_python_script()
            if tool_id == "glm_first_level"
            else _glm_second_level_python_script()
        )
    if recipe_family == "connectivity_matrix":
        return _connectivity_matrix_python_script()
    if recipe_family == "seed_based_connectivity":
        return _seed_based_connectivity_python_script()
    if recipe_family == "mvpa":
        return _mvpa_python_script()
    if recipe_family == "temporal_decoding":
        return _temporal_decoding_python_script()
    if recipe_family == "encoding_models":
        return _encoding_models_python_script()
    if recipe_family == "searchlight":
        return _searchlight_python_script()
    raise ValueError(f"Unsupported direct python recipe family: {recipe_family}")


def _build_direct_family_python_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    recipe_family = str(metadata.get("recipe_family") or "").strip()
    recipe = {
        "dependencies": {"python_packages": metadata["python_packages"]},
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [
            "python -m venv .venv",
            ". .venv/bin/activate",
            "python -m pip install --upgrade pip",
            "pip install "
            + " ".join(shlex.quote(pkg) for pkg in metadata["python_packages"]),
        ],
        "run_command": f"python {script_name}",
        "params_json": _json_text(params),
        "files": {
            script_name: _direct_python_script_for_family(tool_id, recipe_family),
            "params.json": _json_text(params),
        },
    }
    recipe = _attach_python_pack_contract(
        recipe,
        tool_id=tool_id,
        params=params,
        metadata=metadata,
        spec=spec,
        workflow_entry=workflow_entry,
        execution_mode="embedded_python",
        script_name=script_name,
    )
    return recipe, "runnable"


def _default_dockerfile(python_packages: list[str], script_name: str) -> str:
    install_args = " ".join(
        shlex.quote(pkg) for pkg in python_packages or ["brain_researcher"]
    )
    return (
        "FROM python:3.11-slim\n"
        "WORKDIR /work\n"
        "RUN python -m pip install --upgrade pip\n"
        f"RUN pip install --no-cache-dir {install_args}\n"
        f'CMD ["python", "{script_name}"]\n'
    )


def _env_exports(required_env_vars: list[str]) -> list[str]:
    return [f'export {name}="<set-me>"' for name in required_env_vars]


def _rest_connectome_python_script() -> str:
    return (
        "import json\n"
        "import importlib\n"
        "import os\n"
        "import re\n"
        "import shutil\n"
        "from pathlib import Path\n\n"
        "import nibabel as nib\n"
        "import numpy as np\n"
        "from brain_researcher.core.analysis.connectivity_contracts import build_feature_contract, safe_fisher_z, write_feature_contract\n"
        "from nilearn import datasets\n"
        "from nilearn.connectome import ConnectivityMeasure\n"
        "from nilearn.maskers import NiftiLabelsMasker\n\n"
        "def _parse_schaefer_rois(name: str) -> int:\n"
        '    match = re.search(r"(\\d+)", name)\n'
        "    return int(match.group(1)) if match else 200\n\n"
        "def _parse_schaefer_networks(name: str) -> int:\n"
        "    lowered = name.lower()\n"
        "    if '17network' in lowered or '_17' in lowered:\n"
        "        return 17\n"
        "    return 7\n\n"
        "def _bids_entities(path: Path) -> dict[str, str]:\n"
        "    name = path.name\n"
        "    stem = name[:-7] if name.endswith('.nii.gz') else path.stem\n"
        "    entities = {}\n"
        "    for match in re.finditer(r'(?:^|_)([A-Za-z0-9]+)-([^_]+)', stem):\n"
        "        entities[match.group(1)] = match.group(2)\n"
        "    return entities\n\n"
        "def _normalize_res(value: str | int | None) -> str | None:\n"
        "    if value is None:\n"
        "        return None\n"
        "    text = str(value).strip().lower()\n"
        "    if not text:\n"
        "        return None\n"
        "    if text.endswith('mm'):\n"
        "        text = text[:-2]\n"
        "    if text.isdigit():\n"
        "        text = str(int(text))\n"
        "    return text or None\n\n"
        "def _template_candidates(space: str | None) -> list[str]:\n"
        "    explicit = (space or '').strip()\n"
        "    if explicit.startswith('tpl-'):\n"
        "        explicit = explicit[4:]\n"
        "    defaults = ['MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'MNI152Lin']\n"
        "    alias_map = {\n"
        "        'MNI152': defaults,\n"
        "        'FSLMNI152': ['MNI152NLin6Asym', 'MNI152Lin'],\n"
        "    }\n"
        "    candidates = []\n"
        "    if explicit:\n"
        "        candidates.extend(alias_map.get(explicit, [explicit]))\n"
        "    candidates.extend(defaults)\n"
        "    ordered = []\n"
        "    seen = set()\n"
        "    for candidate in candidates:\n"
        "        if not candidate or candidate in seen:\n"
        "            continue\n"
        "        seen.add(candidate)\n"
        "        ordered.append(candidate)\n"
        "    return ordered\n\n"
        "def _find_local_templateflow_schaefer(atlas_name: str, img_path: Path) -> Path | None:\n"
        "    roots = []\n"
        "    tf_home = os.getenv('TEMPLATEFLOW_HOME', '').strip()\n"
        "    if tf_home:\n"
        "        root = Path(tf_home).expanduser().resolve()\n"
        "        if root.exists() and root.is_dir():\n"
        "            roots.append(root)\n"
        "    for item in [entry.strip() for entry in os.getenv('BR_ATLAS_SEARCH_ROOTS', '').split(',') if entry.strip()]:\n"
        "        root = Path(item).expanduser().resolve()\n"
        "        if root.exists() and root.is_dir():\n"
        "            roots.append(root)\n"
        "    if not roots:\n"
        "        return None\n"
        "    ref_entities = _bids_entities(img_path)\n"
        "    wanted_space = ref_entities.get('space') or ref_entities.get('tpl')\n"
        "    wanted_res = _normalize_res(ref_entities.get('res'))\n"
        "    n_rois = _parse_schaefer_rois(atlas_name)\n"
        "    n_networks = _parse_schaefer_networks(atlas_name)\n"
        "    candidates = []\n"
        "    seen = set()\n"
        "    for root in roots:\n"
        "        for path in sorted(root.rglob('*.nii*')):\n"
        "            key = str(path)\n"
        "            if key in seen:\n"
        "                continue\n"
        "            seen.add(key)\n"
        "            name = path.name\n"
        "            if 'atlas-Schaefer2018' not in name or 'dseg' not in name:\n"
        "                continue\n"
        "            desc_match = re.search(r'desc-(\\d+)Parcels(\\d+)Networks', name)\n"
        "            if desc_match is None:\n"
        "                continue\n"
        "            if int(desc_match.group(1)) != n_rois or int(desc_match.group(2)) != n_networks:\n"
        "                continue\n"
        "            entities = _bids_entities(path)\n"
        "            score = (\n"
        "                int(not wanted_space or entities.get('tpl') == wanted_space),\n"
        "                int(wanted_res is None or _normalize_res(entities.get('res')) == wanted_res),\n"
        "                str(path),\n"
        "            )\n"
        "            candidates.append((score, path))\n"
        "    if candidates:\n"
        "        candidates.sort(key=lambda item: item[0])\n"
        "        return candidates[-1][1]\n"
        "    try:\n"
        "        templateflow_api = importlib.import_module('templateflow.api')\n"
        "    except ImportError:\n"
        "        return None\n"
        "    for template in _template_candidates(wanted_space):\n"
        "        query_resolutions = [int(wanted_res)] if wanted_res and wanted_res.isdigit() else []\n"
        "        query_resolutions.append(None)\n"
        "        for query_resolution in query_resolutions:\n"
        "            query = {\n"
        "                'atlas': 'Schaefer2018',\n"
        "                'desc': f'{n_rois}Parcels{n_networks}Networks',\n"
        "                'suffix': 'dseg',\n"
        "                'extension': ['.nii.gz', '.nii'],\n"
        "            }\n"
        "            if query_resolution is not None:\n"
        "                query['resolution'] = query_resolution\n"
        "            try:\n"
        "                fetched = templateflow_api.get(template, raise_empty=True, **query)\n"
        "            except Exception:\n"
        "                continue\n"
        "            fetched_paths = [Path(fetched)] if isinstance(fetched, (str, os.PathLike)) else [Path(p) for p in fetched]\n"
        "            for path in fetched_paths:\n"
        "                try:\n"
        "                    if path.is_file() and path.stat().st_size > 0:\n"
        "                        return path\n"
        "                except OSError:\n"
        "                    continue\n"
        "    return None\n\n"
        "def _prepare_atlas(params: dict, img_path: Path, atlas_dir: Path) -> Path:\n"
        '    atlas_name = str(params.get("atlas_name") or "Schaefer2018_200")\n'
        '    atlas_path = params.get("atlas_path")\n'
        "    atlas_dir.mkdir(parents=True, exist_ok=True)\n"
        "    if atlas_path:\n"
        "        src = Path(atlas_path).expanduser().resolve()\n"
        "        dst = atlas_dir / src.name\n"
        "        if dst != src:\n"
        "            shutil.copyfile(src, dst)\n"
        "        return dst\n"
        "    if atlas_name.lower() in {'synthetic', 'demo', 'test'}:\n"
        "        img = nib.load(str(img_path))\n"
        "        shape = img.shape[:3]\n"
        "        data = np.zeros(shape, dtype=np.int16)\n"
        "        midpoint = max(1, shape[0] // 2)\n"
        "        data[:midpoint, :, :] = 1\n"
        "        data[midpoint:, :, :] = 2\n"
        '        out_path = atlas_dir / "synthetic_atlas.nii.gz"\n'
        "        nib.save(nib.Nifti1Image(data, affine=img.affine), str(out_path))\n"
        "        return out_path\n"
        "    if atlas_name.lower().startswith('schaefer2018'):\n"
        "        local_atlas = _find_local_templateflow_schaefer(atlas_name, img_path)\n"
        "        if local_atlas is not None:\n"
        "            dst = atlas_dir / local_atlas.name\n"
        "            if dst != local_atlas:\n"
        "                shutil.copyfile(local_atlas, dst)\n"
        "            return dst\n"
        "        atlas = datasets.fetch_atlas_schaefer_2018(\n"
        "            n_rois=_parse_schaefer_rois(atlas_name),\n"
        "            resolution_mm=2,\n"
        "            yeo_networks=_parse_schaefer_networks(atlas_name),\n"
        "            data_dir=str(atlas_dir),\n"
        "        )\n"
        "        src = Path(atlas.maps)\n"
        "        dst = atlas_dir / src.name\n"
        "        if dst != src:\n"
        "            shutil.copyfile(src, dst)\n"
        "        return dst\n"
        "    raise ValueError(f'Unsupported atlas_name for direct recipe: {atlas_name}')\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'output_dir = Path(params["output_dir"]).expanduser().resolve()\n'
        "output_dir.mkdir(parents=True, exist_ok=True)\n"
        'img_path = Path(params["img"]).expanduser().resolve()\n'
        'atlas_dir = output_dir / "atlas"\n'
        'timeseries_dir = output_dir / "timeseries"\n'
        "timeseries_dir.mkdir(parents=True, exist_ok=True)\n"
        "atlas_path = _prepare_atlas(params, img_path, atlas_dir)\n"
        "masker = NiftiLabelsMasker(\n"
        "    labels_img=str(atlas_path),\n"
        '    standardize="zscore_sample" if bool(params.get("standardize", True)) else False,\n'
        "    standardize_confounds=False,\n"
        '    detrend=bool(params.get("detrend", True)),\n'
        '    t_r=params.get("tr"),\n'
        '    low_pass=params.get("low_pass"),\n'
        '    high_pass=params.get("high_pass"),\n'
        "    keep_masked_labels=False,\n"
        ")\n"
        "timeseries = np.asarray(masker.fit_transform(str(img_path)), dtype=float)\n"
        'timeseries_npy = timeseries_dir / "timeseries.npy"\n'
        'timeseries_csv = timeseries_dir / "timeseries.csv"\n'
        "np.save(timeseries_npy, timeseries)\n"
        "np.savetxt(timeseries_csv, timeseries, delimiter=',')\n"
        'kind = str(params.get("connectivity_kind") or "correlation")\n'
        'measure = ConnectivityMeasure(kind=kind, standardize="zscore_sample")\n'
        "matrix = measure.fit_transform([timeseries])\n"
        "matrix, fisher_z_diagnostics = safe_fisher_z(\n"
        "    matrix,\n"
        "    f'rest_connectome_corrmat(kind={kind})',\n"
        "    return_diagnostics=True,\n"
        ")\n"
        'matrix_file = output_dir / "connectivity_matrix.npy"\n'
        "np.save(matrix_file, matrix)\n"
        "outputs = {\n"
        '    "atlas_path": str(atlas_path),\n'
        '    "timeseries": str(timeseries_npy),\n'
        '    "timeseries_csv": str(timeseries_csv),\n'
        '    "matrix": str(matrix_file),\n'
        '    "connectivity_matrix": str(matrix_file),\n'
        "}\n"
        "summary = {\n"
        '    "kind": kind,\n'
        '    "n_timepoints": int(timeseries.shape[0]),\n'
        '    "n_regions": int(timeseries.shape[1]) if timeseries.ndim > 1 else 1,\n'
        '    "fisher_z_applied": True,\n'
        '    "fisher_z_diagnostics": fisher_z_diagnostics,\n'
        "}\n"
        "try:\n"
        "    cov_estimator_obj = getattr(measure, 'cov_estimator_', None) or getattr(measure, 'cov_estimator', None)\n"
        "    cov_estimator_name = type(cov_estimator_obj).__name__ if cov_estimator_obj is not None else None\n"
        "    contract = build_feature_contract(\n"
        "        matrix,\n"
        "        matrix_kind=kind,\n"
        "        source_level='roi_timeseries',\n"
        "        n_rois=int(timeseries.shape[1]) if timeseries.ndim > 1 else 1,\n"
        "        n_timepoints=int(timeseries.shape[0]),\n"
        "        effective_n_timepoints=int(timeseries.shape[0]),\n"
        "        covariance_estimator=cov_estimator_name,\n"
        "        fisher_z_diagnostics=fisher_z_diagnostics,\n"
        "        extras={'atlas_path': str(atlas_path)},\n"
        "    )\n"
        "    outputs['feature_contract'] = str(write_feature_contract(contract, output_dir))\n"
        "except Exception as exc:\n"
        "    summary['feature_contract_warning'] = f'feature_contract sidecar emission failed: {exc!r}'\n"
        "print(json.dumps({'outputs': outputs, 'summary': summary}, indent=2, sort_keys=True))\n"
    )


def _build_rest_connectome_python_recipe(
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    script_name = "run_workflow_rest_connectome_e2e.py"
    setup_commands, extra_env_vars = _python_setup_commands(metadata["python_packages"])
    recipe = {
        "dependencies": {"python_packages": metadata["python_packages"]},
        "required_env_vars": metadata["required_env_vars"] + extra_env_vars,
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": f"python {script_name}",
        "params_json": _json_text(params),
        "files": {
            script_name: _rest_connectome_python_script(),
            "params.json": _json_text(params),
        },
    }
    recipe = _attach_python_pack_contract(
        recipe,
        tool_id="workflow_rest_connectome_e2e",
        params=params,
        metadata=metadata,
        spec=spec,
        workflow_entry=workflow_entry,
        execution_mode="embedded_python",
        script_name=script_name,
    )
    return recipe, "runnable"


def _build_generic_python_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    setup_commands, extra_env_vars = _python_setup_commands(metadata["python_packages"])
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
        },
        "required_env_vars": metadata["required_env_vars"] + extra_env_vars,
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": f"python {script_name}",
        "params_json": _json_text(params),
        "files": {
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    recipe = _attach_python_pack_contract(
        recipe,
        tool_id=tool_id,
        params=params,
        metadata=metadata,
        spec=spec,
        workflow_entry=workflow_entry,
        execution_mode="local_tool",
    )
    return recipe, "runnable"


def _build_generic_neurodesk_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    module_cmd = " && ".join(
        [f"module load {module}" for module in metadata["neurodesk_modules"]]
    )
    run_command = (
        f"{module_cmd} && python {script_name}"
        if module_cmd
        else f"python {script_name}"
    )
    setup_commands = [
        f"module load {module}" for module in metadata["neurodesk_modules"]
    ]
    setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "neurodesk_modules": metadata["neurodesk_modules"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(params),
        "files": {
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    return recipe, "runnable"


def _build_generic_container_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    image_tag = f"brain-researcher-recipe-{slug}"
    dockerfile = _default_dockerfile(metadata["python_packages"], script_name)
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "container_images": metadata["container_images"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [
            f"docker build -t {image_tag} -f Dockerfile .",
        ],
        "run_command": (
            f'docker run --rm -v "$PWD":/work -w /work {image_tag} python {script_name}'
        ),
        "params_json": _json_text(params),
        "files": {
            "Dockerfile": dockerfile,
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    return recipe, "runnable"


def _build_generic_slurm_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    module_lines = [f"module load {module}" for module in metadata["neurodesk_modules"]]
    env_lines = _env_exports(metadata["required_env_vars"])
    command = f"python {script_name}"

    if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
        rendered = sherlock_render_sbatch_script(
            "cpu_single",
            cluster_profile=cluster_profile,
            job_name=f"br-{slug}",
            module_lines=module_lines or None,
            env_lines=env_lines or None,
            command=command,
        )
        script_text = str(rendered.get("script_text") or "")
    else:
        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name=br-{slug}",
            "#SBATCH --time=24:00:00",
            "#SBATCH --cpus-per-task=8",
            "#SBATCH --mem=16G",
            "#SBATCH --output=slurm-%j.out",
            "#SBATCH --error=slurm-%j.err",
            "",
            "set -euo pipefail",
            "",
        ]
        lines.extend(module_lines)
        if module_lines:
            lines.append("")
        lines.extend(env_lines)
        if env_lines:
            lines.append("")
        lines.append(command)
        script_text = "\n".join(lines) + "\n"

    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "neurodesk_modules": metadata["neurodesk_modules"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [],
        "run_command": "sbatch job.sbatch",
        "params_json": _json_text(params),
        "files": {
            "job.sbatch": script_text,
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    return recipe, "runnable"


def _preprocessing_post_qc_script() -> str:
    return (
        "import json\n"
        "from html import escape\n"
        "from pathlib import Path\n\n"
        "import pandas as pd\n\n"
        "def _load_qc_table(qc_tsv: str | None, mriqc_dir: Path, modality: str) -> pd.DataFrame:\n"
        "    if qc_tsv:\n"
        "        return pd.read_csv(qc_tsv, sep='\\t')\n"
        "    candidates = [\n"
        "        mriqc_dir / f'group_{modality}.tsv',\n"
        "        mriqc_dir / f'group_{modality}.csv',\n"
        "        mriqc_dir / 'group_bold.tsv',\n"
        "        mriqc_dir / 'group_T1w.tsv',\n"
        "    ]\n"
        "    table_path = next((path for path in candidates if path.exists()), None)\n"
        "    if table_path is None:\n"
        "        raise FileNotFoundError('MRIQC group table not found')\n"
        "    return pd.read_csv(table_path, sep='\\t' if table_path.suffix == '.tsv' else ',')\n\n"
        "def _write_dashboard(df: pd.DataFrame, output_html: Path, title: str) -> None:\n"
        "    html = [\n"
        "        \"<html><head><meta charset='utf-8'>\",\n"
        "        f'<title>{escape(title)}</title>',\n"
        '        "<style>body{font-family:system-ui,Segoe UI,Arial;margin:24px} table{border-collapse:collapse} td,th{border:1px solid #ddd;padding:6px 8px} th{background:#f6f6f6}</style>",\n'
        '        "</head><body>",\n'
        "        f'<h1>{escape(title)}</h1>',\n"
        "        f'<p>Rows: {df.shape[0]} | Columns: {df.shape[1]}</p>',\n"
        "        df.head(50).to_html(index=False, escape=True),\n"
        '        "</body></html>",\n'
        "    ]\n"
        "    output_html.write_text('\\n'.join(html), encoding='utf-8')\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'output_dir = Path(params["output_dir"]).expanduser().resolve()\n'
        'qc_dir = output_dir / "qc"\n'
        "qc_dir.mkdir(parents=True, exist_ok=True)\n"
        'qc_table_path = qc_dir / "qc_table.csv"\n'
        'outliers_path = qc_dir / "qc_outliers.csv"\n'
        'summary_path = qc_dir / "qc_summary.json"\n'
        'dashboard_path = qc_dir / "index.html"\n'
        "df = _load_qc_table(\n"
        '    params.get("qc_tsv"),\n'
        '    output_dir / "mriqc",\n'
        '    str(params.get("modality") or "bold"),\n'
        ")\n"
        "df.to_csv(qc_table_path, index=False)\n"
        'metric = str(params.get("outlier_metric") or "fd_mean")\n'
        'z_threshold = float(params.get("outlier_z", 3.0))\n'
        "if metric in df.columns:\n"
        "    series = pd.to_numeric(df[metric], errors='coerce')\n"
        "    mu = float(series.mean(skipna=True))\n"
        "    sigma = float(series.std(skipna=True)) or 0.0\n"
        "    if sigma <= 1e-12:\n"
        "        flags = series.notna() & False\n"
        "    else:\n"
        "        flags = ((series - mu) / sigma).abs() >= z_threshold\n"
        "else:\n"
        "    flags = pd.Series([False] * len(df))\n"
        "df_out = df.copy()\n"
        "df_out['outlier'] = flags.fillna(False)\n"
        "df_out.to_csv(outliers_path, index=False)\n"
        "numeric = df_out.select_dtypes(include='number')\n"
        "summary_payload = {\n"
        "    'n_rows': int(df_out.shape[0]),\n"
        "    'n_cols': int(df_out.shape[1]),\n"
        "    'columns': list(df_out.columns),\n"
        "    'metric': metric,\n"
        "    'z_threshold': z_threshold,\n"
        "    'n_outliers': int(flags.sum()),\n"
        "    'numeric_summary': numeric.describe().to_dict() if not numeric.empty else {},\n"
        "}\n"
        "summary_path.write_text(json.dumps(summary_payload, indent=2), encoding='utf-8')\n"
        "_write_dashboard(df_out, dashboard_path, str(params.get('dashboard_title') or 'QC Summary'))\n"
        "print(json.dumps({\n"
        '    "outputs": {\n'
        '        "qc_table": str(qc_table_path),\n'
        '        "outliers_table": str(outliers_path),\n'
        '        "summary": str(summary_path),\n'
        '        "dashboard": str(dashboard_path),\n'
        "    },\n"
        '    "summary": summary_payload,\n'
        "}, indent=2, sort_keys=True, default=str))\n"
    )


def _preprocessing_neurodesk_script() -> str:
    return (
        "import json\n"
        "import subprocess\n"
        "from pathlib import Path\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'output_dir = str(Path(params["output_dir"]))\n'
        "subprocess.run([\n"
        '    "fmriprep",\n'
        '    params["bids_dir"],\n'
        '    str(Path(output_dir) / "fmriprep"),\n'
        '    "participant",\n'
        "], check=True)\n"
        "subprocess.run([\n"
        '    "mriqc",\n'
        '    params["bids_dir"],\n'
        '    str(Path(output_dir) / "mriqc"),\n'
        '    "participant",\n'
        "], check=True)\n"
        'subprocess.run(["python", "post_qc.py"], check=True)\n'
    )


def _preprocessing_container_script(container_images: dict[str, Any]) -> str:
    fmriprep_image = str(container_images.get("fmriprep") or "nipreps/fmriprep:23.2.3")
    mriqc_image = str(container_images.get("mriqc") or "nipreps/mriqc:24.0.2")
    return (
        "import json\n"
        "import subprocess\n"
        "from pathlib import Path\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'bids_dir = str(Path(params["bids_dir"]).resolve())\n'
        'output_dir = str(Path(params["output_dir"]).resolve())\n'
        "docker_mounts = [\n"
        '    "-v", f"{bids_dir}:{bids_dir}",\n'
        '    "-v", f"{output_dir}:{output_dir}",\n'
        "]\n"
        "subprocess.run([\n"
        '    "docker", "run", "--rm", *docker_mounts,\n'
        f'    "{fmriprep_image}",\n'
        "    bids_dir,\n"
        '    str(Path(output_dir) / "fmriprep"),\n'
        '    "participant",\n'
        "], check=True)\n"
        "subprocess.run([\n"
        '    "docker", "run", "--rm", *docker_mounts,\n'
        f'    "{mriqc_image}",\n'
        "    bids_dir,\n"
        '    str(Path(output_dir) / "mriqc"),\n'
        '    "participant",\n'
        "], check=True)\n"
        'subprocess.run(["python", "post_qc.py"], check=True)\n'
    )


def _build_preprocessing_qc_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    payload = _minimal_preprocessing_qc_payload(params)
    fmriprep_payload = _minimal_fmriprep_payload(
        {
            "bids_dir": payload["bids_dir"],
            "output_dir": payload["fmriprep_output_dir"],
            "participant_label": payload["participant_label"],
            "work_dir": payload["fmriprep_work_dir"],
            "fs_license_file": payload["fs_license_file"],
            "output_spaces": payload["output_spaces"],
            "bids_filter_file": payload["bids_filter_file"],
            "n_cpus": payload["n_cpus"],
            "omp_nthreads": payload["omp_nthreads"],
            "mem_mb": payload["mem_mb"],
            "extra_args": payload["fmriprep_extra_args"],
        }
    )
    mriqc_payload = _minimal_mriqc_payload(
        {
            "bids_dir": payload["bids_dir"],
            "output_dir": payload["mriqc_output_dir"],
            "analysis_level": payload["analysis_level"],
            "participant_label": payload["participant_label"],
            "modalities": payload["modalities"],
            "work_dir": payload["mriqc_work_dir"],
            "bids_filter_file": payload["bids_filter_file"],
            "n_procs": payload["n_procs"],
            "mem_gb": payload["mem_gb"],
            "extra_args": payload["mriqc_extra_args"],
        }
    )

    script_name = "run_workflow_preprocessing_qc.sh"
    fmriprep_script_name = "run_fmriprep.sh"
    mriqc_script_name = "run_mriqc.sh"
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_preprocessing_qc",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary=(
                "single-subject fMRIPrep + MRIQC example with downstream QC "
                "aggregation (4 CPUs for fMRIPrep, 4 processes / 8 GB for MRIQC)"
            ),
        ),
        "params.json": _json_text(payload),
        "post_qc.py": _preprocessing_post_qc_script(),
        fmriprep_script_name: _build_fmriprep_script(
            "container" if target_runtime == "container" else "host",
            fmriprep_payload,
        ),
        mriqc_script_name: _build_mriqc_script(
            "container" if target_runtime == "container" else "host",
            mriqc_payload,
        ),
        script_name: "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f"bash {fmriprep_script_name}",
                f"bash {mriqc_script_name}",
                "python post_qc.py",
                "",
            ]
        ),
    }

    dependency_block = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"bash {script_name}"
    warnings = [
        "This recipe runs a lightweight QC post-processing step after fMRIPrep and MRIQC complete.",
        "The generated shell scripts are intentionally single-subject and resource-limited.",
        "A valid FreeSurfer license file is required for the fMRIPrep portion of the workflow.",
    ]

    if target_runtime == "neurodesk":
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    elif target_runtime == "container":
        for image_name in ("fmriprep", "mriqc"):
            image = str(metadata["container_images"].get(image_name) or "")
            if image:
                setup_commands.append(f"docker pull {image}")
    else:
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow-preprocessing-qc",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"bash {script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            files["job.sbatch"] = "\n".join(
                [
                    "#!/bin/bash",
                    "#SBATCH --job-name=br-workflow-preprocessing-qc",
                    "#SBATCH --time=24:00:00",
                    "#SBATCH --cpus-per-task=8",
                    "#SBATCH --mem=32G",
                    "#SBATCH --output=slurm-%j.out",
                    "#SBATCH --error=slurm-%j.err",
                    "",
                    "set -euo pipefail",
                    "",
                    *module_lines,
                    *env_lines,
                    f"bash {script_name}",
                    "",
                ]
            )
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": warnings,
    }
    return recipe, "runnable"


def _minimal_task_glm_group_payload(params: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/task_glm_group_minimal_execute"
        ),
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "fmriprep_dir": str(
            params.get("fmriprep_dir")
            or "/data/openneuro/ds000114/derivatives/fmriprep"
        ),
        "task": str(params.get("task") or "linebisection"),
        "participant_label": _normalize_sequence_value(params.get("participant_label"))
        or ["01", "02"],
        "session": str(params.get("session") or ""),
        "space": str(params.get("space") or "MNI152NLin2009cAsym"),
        "contrast_name": str(params.get("contrast_name") or ""),
        "dry_run": bool(params.get("dry_run", False)),
    }
    direct_imgs = _normalize_sequence_value(params.get("img"))
    direct_events = _normalize_sequence_value(params.get("events"))
    if direct_imgs:
        payload["img"] = direct_imgs
    if direct_events:
        payload["events"] = direct_events
    if params.get("t_r") is not None:
        payload["t_r"] = _coerce_float_value(params.get("t_r"), 0.0)
    if params.get("smoothing_fwhm") is not None:
        payload["smoothing_fwhm"] = _coerce_float_value(
            params.get("smoothing_fwhm"), 0.0
        )
    if params.get("mask_img"):
        payload["mask_img"] = str(params.get("mask_img"))
    return payload


def _task_glm_group_container_dockerfile(
    python_packages: list[str],
    script_name: str,
) -> str:
    install_args = " ".join(
        shlex.quote(pkg) for pkg in python_packages if pkg != "brain_researcher"
    )
    extra_install = f" {install_args}" if install_args else ""
    return (
        "FROM python:3.11-slim\n"
        "WORKDIR /work\n"
        "COPY . /work\n"
        "RUN python -m pip install --upgrade pip\n"
        f"RUN pip install --no-cache-dir -e .{extra_install}\n"
        f'CMD ["python", "{script_name}"]\n'
    )


def _build_task_glm_group_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    payload = _minimal_task_glm_group_payload(params)
    script_name = "run_workflow_task_glm_group.py"
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_task_glm_group",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary=(
                "small group-level task GLM example that prefers "
                "bids_dir + fmriprep_dir + task inputs and can preview "
                "or execute the resolved first-level + second-level plan"
            ),
        ),
        script_name: _default_runtime_script("workflow_task_glm_group"),
        "params.json": _json_text(payload),
    }
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"python {script_name}"
    warnings = [
        "This workflow now prefers bids_dir + fmriprep_dir + task inputs; direct img/events remain available for compatibility.",
        "Set dry_run=true in params.json to preview subject resolution and planned second-level execution without running Nilearn GLMs.",
        "If contrast_name is empty, the runtime attempts to infer a common trial_type across subjects and otherwise falls back to the first available contrast per subject.",
    ]

    if target_runtime == "container":
        image_tag = "brain-researcher-recipe-workflow-task-glm-group"
        files["Dockerfile"] = _task_glm_group_container_dockerfile(
            metadata["python_packages"], script_name
        )
        setup_commands.append(f"docker build -t {image_tag} -f Dockerfile .")
        run_command = (
            f'docker run --rm -v "$PWD":/work -w /work {image_tag} python {script_name}'
        )
    elif target_runtime == "slurm":
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow-task-glm-group",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"python {script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            files["job.sbatch"] = "\n".join(
                [
                    "#!/bin/bash",
                    "#SBATCH --job-name=br-workflow-task-glm-group",
                    "#SBATCH --time=08:00:00",
                    "#SBATCH --cpus-per-task=4",
                    "#SBATCH --mem=12G",
                    "#SBATCH --output=slurm-%j.out",
                    "#SBATCH --error=slurm-%j.err",
                    "",
                    "set -euo pipefail",
                    "",
                    *module_lines,
                    *env_lines,
                    f"python {script_name}",
                    "",
                ]
            )
        run_command = "sbatch job.sbatch"
    else:
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": warnings,
    }
    return recipe, "runnable"


def _minimal_dwi_connectome_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(
        params.get("qsirecon_extra_args", params.get("extra_args"))
    )
    return {
        "qsiprep_dir": str(
            params.get("qsiprep_dir") or "/data/openneuro/ds000117/derivatives/qsiprep"
        ),
        "qsirecon_dir": str(params.get("qsirecon_dir") or ""),
        "output_dir": str(
            params.get("output_dir")
            or "./outputs/out/dwi_connectome_single_subject_minimal"
        ),
        "atlas": str(
            params.get("atlas")
            or "/data/reference/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
        ),
        "recon_spec": str(
            params.get("recon_spec") or "mrtrix_multishell_msmt_ACT-hsvs"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/dwi_connectome_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _build_dwi_connectome_postprocess_script() -> str:
    return dedent("""
        import json
        import os
        import sys
        from pathlib import Path

        from brain_researcher.services.tools.dwi_connectome_workflow import (
            collect_qsirecon_derivatives,
            materialize_connectome_from_existing,
            materialize_connectome_from_tractogram,
            pick_primary_connectome,
            pick_primary_tractogram,
        )

        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        output_dir = Path(str(params["output_dir"])).expanduser().resolve()
        qsirecon_dir = Path(
            os.environ.get("RESOLVED_QSIRECON_DIR")
            or params.get("qsirecon_dir")
            or output_dir / "qsirecon"
        ).expanduser().resolve()
        derivatives = collect_qsirecon_derivatives(qsirecon_dir)
        tractogram = pick_primary_tractogram(derivatives)
        connectome = pick_primary_connectome(derivatives)
        atlas = str(params.get("atlas") or "").strip()
        sc_dir = output_dir / "sc"
        sc_dir.mkdir(parents=True, exist_ok=True)

        if tractogram and atlas:
            outputs, summary = materialize_connectome_from_tractogram(
                tractogram_path=tractogram,
                atlas_path=atlas,
                output_dir=sc_dir,
            )
        elif connectome:
            outputs, summary = materialize_connectome_from_existing(
                connectome_path=connectome,
                output_dir=sc_dir,
            )
        else:
            raise SystemExit(
                "No tractogram/connectome found under the resolved QSIRecon directory"
            )

        payload = {
            "outputs": {
                **outputs,
                "qsirecon_dir": str(qsirecon_dir),
                "tractogram": tractogram,
                "source_connectome": connectome,
            },
            "summary": {
                **summary,
                "route": "qsirecon_derivatives",
                "available_derivatives": derivatives,
            },
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        """).strip() + "\n"


def _build_dwi_connectome_runner_script() -> str:
    return dedent("""
        import subprocess

        completed = subprocess.run(["bash", "run_workflow_dwi_connectome.sh"], check=False)
        raise SystemExit(completed.returncode)
        """).strip() + "\n"


def _build_dwi_connectome_script(target_runtime: str, payload: dict[str, Any]) -> str:
    command_tokens = ["qsirecon" if target_runtime != "container" else "docker"]
    resolved_qsirecon_dir = '"${QSIRECON_DIR:-$OUTPUT_DIR/qsirecon}"'
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$QSIPREP_DIR:$QSIPREP_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
            ]
        )
        if payload["fs_license_file"]:
            command_tokens.extend(
                ["-v", '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"']
            )
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("qsirecon") or "pennlinc/qsirecon:1.1.1")
                ),
                '"$QSIPREP_DIR"',
                resolved_qsirecon_dir,
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$QSIPREP_DIR"', resolved_qsirecon_dir, "participant"])
    command_tokens.extend(["--recon-spec", '"$RECON_SPEC"'])
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if payload["fs_license_file"]:
        if target_runtime == "container":
            command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
        else:
            command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("QSIPREP_DIR", str(payload["qsiprep_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default("ATLAS", str(payload["atlas"])),
        _render_shell_default("RECON_SPEC", str(payload["recon_spec"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        _render_shell_default("QSIRECON_DIR", str(payload["qsirecon_dir"])),
    ]
    if payload["fs_license_file"]:
        lines.append(
            'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"'
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            'RESOLVED_QSIRECON_DIR="${QSIRECON_DIR:-$OUTPUT_DIR/qsirecon}"',
            'if [[ -n "${QSIRECON_DIR:-}" && -d "$QSIRECON_DIR" ]]; then',
            '  echo "Using existing QSIRecon derivatives at $QSIRECON_DIR"',
            "else",
            f"  {_render_shell_command(command_tokens)}",
            "fi",
            'export RESOLVED_QSIRECON_DIR="${RESOLVED_QSIRECON_DIR}"',
            "python postprocess_dwi_connectome.py",
            "",
        ]
    )
    return "\n".join(lines)


def _build_dwi_connectome_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    payload = _minimal_dwi_connectome_payload(params)
    shell_script_name = "run_workflow_dwi_connectome.sh"
    python_script_name = "run_workflow_dwi_connectome.py"
    script_text = _build_dwi_connectome_script(
        "container" if target_runtime == "container" else "host", payload
    )
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_dwi_connectome",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=python_script_name,
            minimal_summary=(
                "single-subject derivative-first DWI connectome example that prefers "
                "existing qsirecon_dir and otherwise runs QSIRecon before "
                "materializing a standardized connectome"
            ),
        ),
        python_script_name: _build_dwi_connectome_runner_script(),
        shell_script_name: script_text,
        "postprocess_dwi_connectome.py": _build_dwi_connectome_postprocess_script(),
        "params.json": _json_text(payload),
    }
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"python {python_script_name}"

    if target_runtime == "neurodesk":
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    elif target_runtime == "container":
        image = str(
            metadata["container_images"].get("qsirecon")
            or get_container_image("qsirecon")
            or "pennlinc/qsirecon:1.1.1"
        )
        setup_commands.append(f"docker pull {image}")
    else:
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow_dwi_connectome",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"python {python_script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            lines = [
                "#!/bin/bash",
                "#SBATCH --job-name=br-workflow_dwi_connectome",
                "#SBATCH --time=24:00:00",
                "#SBATCH --cpus-per-task=4",
                "#SBATCH --mem=16G",
                "#SBATCH --output=slurm-%j.out",
                "#SBATCH --error=slurm-%j.err",
                "",
                "set -euo pipefail",
                "",
                *module_lines,
                *env_lines,
                f"python {python_script_name}",
                "",
            ]
            files["job.sbatch"] = "\n".join(lines)
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": [
            "This minimal recipe prefers existing qsirecon_dir inputs; otherwise it runs QSIRecon against qsiprep_dir before post-processing.",
            "Provide an atlas aligned to the reconstruction space if you want a tractogram-derived connectome instead of normalizing an existing recon connectome.",
            "The legacy raw dwi/bvals/bvecs fallback path remains available in the runtime workflow but is intentionally not the primary MCP recipe.",
        ],
    }
    return recipe, "runnable"


def _normalize_sequence_value(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list | tuple | set):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    return [text] if text else []


def _coerce_int_value(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _coerce_float_value(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _render_shell_command(tokens: list[str]) -> str:
    if not tokens:
        return ""
    head, *tail = tokens
    return head + "".join(f" \\\n  {token}" for token in tail)


def _render_shell_default(name: str, value: str) -> str:
    return f'{name}="${{{name}:-{value}}}"'


def _compact_optional_fields(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    compacted = dict(payload)
    for key in keys:
        if compacted.get(key) is None:
            compacted.pop(key, None)
    return compacted


def _recipe_subject_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return _compact_optional_fields(
        {
            "canonical_tool_id": metadata.get("canonical_tool_id"),
            "neurodesk_package_name": metadata.get("neurodesk_package_name"),
            "neurodesk_module_name": metadata.get("neurodesk_module_name"),
            "neurodesk_recommended_version": metadata.get(
                "neurodesk_recommended_version"
            ),
            "neurodesk_available_versions": metadata.get(
                "neurodesk_available_versions"
            ),
            "neurodesk_recommended_module": metadata.get(
                "neurodesk_recommended_module"
            ),
            "neurodesk_available_modules": metadata.get("neurodesk_available_modules"),
            "stable_workflow_pack": metadata.get("stable_workflow_pack"),
            "source_repo": metadata.get("source_repo"),
            "source_paper": metadata.get("source_paper"),
            "tested_release": metadata.get("tested_release"),
            "backend_options": metadata.get("backend_options"),
            "example_dataset": metadata.get("example_dataset"),
            "reference_assets": metadata.get("reference_assets"),
            "artifact_contract": metadata.get("artifact_contract"),
            "acceptance_gate": metadata.get("acceptance_gate"),
            "runbook": metadata.get("runbook"),
        },
        "source_repo",
        "source_paper",
        "tested_release",
    )


def _external_repo_recipe_readme(
    tool_id: str,
    *,
    target_runtime: str,
    metadata: dict[str, Any],
    script_name: str,
    minimal_summary: str,
) -> str:
    example_dataset = (
        metadata.get("example_dataset")
        if isinstance(metadata.get("example_dataset"), dict)
        else {}
    )
    artifact_contract = (
        metadata.get("artifact_contract")
        if isinstance(metadata.get("artifact_contract"), dict)
        else {}
    )
    acceptance_gate = (
        metadata.get("acceptance_gate")
        if isinstance(metadata.get("acceptance_gate"), dict)
        else {}
    )
    required_outputs = _normalize_list(artifact_contract.get("required_outputs"))
    optional_outputs = _normalize_list(artifact_contract.get("optional_outputs"))
    gate_lines = []
    if acceptance_gate.get("execute_gate_script"):
        gate_lines.append(
            f"- Execute gate: `{acceptance_gate['execute_gate_script']} --workflow-id {tool_id}`"
        )
    if acceptance_gate.get("smoke_test"):
        gate_lines.append(f"- Preview smoke: `{acceptance_gate['smoke_test']}`")
    if acceptance_gate.get("execute_gate_test"):
        gate_lines.append(f"- Execute test: `{acceptance_gate['execute_gate_test']}`")
    gate_block = "\n".join(gate_lines) if gate_lines else "- Gate: not declared"
    optional_block = (
        f"- Optional outputs: `{', '.join(optional_outputs)}`"
        if optional_outputs
        else ""
    )
    return dedent(f"""
        # Minimal Execution Recipe: {tool_id}

        - Runtime target: `{target_runtime}`
        - Source repo: `{metadata.get("source_repo") or "unknown"}`
        - Tested release: `{metadata.get("tested_release") or "unspecified"}`
        - Example dataset: `{example_dataset.get("dataset_id") or "unspecified"}`
        - Runbook: `{metadata.get("runbook") or "n/a"}`
        - Generated run command: `bash {script_name}`
        - Minimal profile: {minimal_summary}
        - Required outputs: `{", ".join(required_outputs) or "unspecified"}`
        {optional_block}

        ## Gate

        {gate_block}

        ## Notes

        - The generated shell script is intentionally single-subject and resource-limited.
        - Edit the variable block at the top of the script before running on your environment.
        - `params.json` mirrors the Brain Researcher workflow payload used to derive the script.
        """).strip() + "\n"


def _minimal_fmriprep_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    output_spaces = _normalize_sequence_value(params.get("output_spaces"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--skip-bids-validation" not in extra_args:
        extra_args.append("--skip-bids-validation")
    if "--fs-no-reconall" not in extra_args:
        extra_args.append("--fs-no-reconall")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/fmriprep_single_subject_minimal"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/fmriprep_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "output_spaces": output_spaces or ["MNI152NLin2009cAsym"],
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_preprocessing_qc_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    output_spaces = _normalize_sequence_value(params.get("output_spaces"))
    modalities = _normalize_sequence_value(params.get("modalities"))
    common_extra_args = _normalize_sequence_value(params.get("extra_args"))
    fmriprep_extra_args = _normalize_sequence_value(params.get("fmriprep_extra_args"))
    mriqc_extra_args = _normalize_sequence_value(params.get("mriqc_extra_args"))

    fmriprep_args = [*common_extra_args, *fmriprep_extra_args]
    mriqc_args = [*common_extra_args, *mriqc_extra_args]
    if "--skip-bids-validation" not in fmriprep_args:
        fmriprep_args.append("--skip-bids-validation")
    if "--fs-no-reconall" not in fmriprep_args:
        fmriprep_args.append("--fs-no-reconall")
    if "--no-sub" not in mriqc_args:
        mriqc_args.append("--no-sub")

    output_dir = str(
        params.get("output_dir")
        or "./outputs/out/preprocessing_qc_single_subject_minimal"
    )
    work_dir = str(
        params.get("work_dir")
        or "./outputs/out/preprocessing_qc_single_subject_minimal_work"
    )
    qc_tsv = str(params.get("qc_tsv") or "").strip()
    bids_filter_file = str(params.get("bids_filter_file") or "").strip()
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": output_dir,
        "participant_label": participant_labels or ["01"],
        "analysis_level": str(params.get("analysis_level") or "participant"),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "output_spaces": output_spaces or ["MNI152NLin2009cAsym"],
        "modalities": modalities or ["bold"],
        "modality": str(params.get("modality") or "bold"),
        "bids_filter_file": bids_filter_file,
        "qc_tsv": qc_tsv,
        "outlier_metric": str(params.get("outlier_metric") or "fd_mean"),
        "outlier_z": _coerce_float_value(params.get("outlier_z"), 3.0),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "n_procs": _coerce_int_value(params.get("n_procs"), 4),
        "mem_gb": _coerce_float_value(params.get("mem_gb"), 8.0),
        "fmriprep_output_dir": str(Path(output_dir) / "fmriprep"),
        "mriqc_output_dir": str(Path(output_dir) / "mriqc"),
        "fmriprep_work_dir": str(Path(work_dir) / "fmriprep"),
        "mriqc_work_dir": str(Path(work_dir) / "mriqc"),
        "fmriprep_extra_args": fmriprep_args,
        "mriqc_extra_args": mriqc_args,
        "dry_run": False,
    }


def _minimal_mriqc_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    modalities = _normalize_sequence_value(params.get("modalities"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--no-sub" not in extra_args:
        extra_args.append("--no-sub")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/mriqc_single_subject_minimal"
        ),
        "analysis_level": str(params.get("analysis_level") or "participant"),
        "participant_label": participant_labels or ["01"],
        "modalities": modalities or ["bold"],
        "work_dir": str(
            params.get("work_dir") or "./outputs/out/mriqc_single_subject_minimal_work"
        ),
        "bids_filter_file": str(params.get("bids_filter_file") or ""),
        "n_procs": _coerce_int_value(params.get("n_procs"), 4),
        "mem_gb": _coerce_float_value(params.get("mem_gb"), 8.0),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_qsiprep_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--skip-bids-validation" not in extra_args:
        extra_args.append("--skip-bids-validation")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/qsiprep_single_subject_minimal"
        ),
        "analysis_level": str(params.get("analysis_level") or "participant"),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/qsiprep_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "bids_filter_file": str(params.get("bids_filter_file") or ""),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_smriprep_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    if "--skip-bids-validation" not in extra_args:
        extra_args.append("--skip-bids-validation")
    return {
        "bids_dir": str(params.get("bids_dir") or "/data/openneuro/ds000114/bids"),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/smriprep_single_subject_minimal"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/smriprep_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "bids_filter_file": str(params.get("bids_filter_file") or ""),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_qsirecon_payload(params: dict[str, Any]) -> dict[str, Any]:
    participant_labels = _normalize_sequence_value(params.get("participant_label"))
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    return {
        "qsiprep_dir": str(
            params.get("qsiprep_dir") or "/data/openneuro/ds000114/derivatives/qsiprep"
        ),
        "output_dir": str(
            params.get("output_dir") or "./outputs/out/qsirecon_single_subject_minimal"
        ),
        "recon_spec": str(
            params.get("recon_spec") or "mrtrix_multishell_msmt_ACT-hsvs"
        ),
        "participant_label": participant_labels or ["01"],
        "work_dir": str(
            params.get("work_dir")
            or "./outputs/out/qsirecon_single_subject_minimal_work"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "n_cpus": _coerce_int_value(params.get("n_cpus"), 4),
        "omp_nthreads": _coerce_int_value(params.get("omp_nthreads"), 2),
        "mem_mb": _coerce_int_value(params.get("mem_mb"), 16000),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _minimal_fastsurfer_payload(params: dict[str, Any]) -> dict[str, Any]:
    extra_args = _normalize_sequence_value(params.get("extra_args"))
    runtime = str(params.get("runtime") or "docker").strip().lower()
    if runtime not in {"docker", "apptainer"}:
        runtime = "docker"
    return {
        "t1w_image": str(
            params.get("t1w_image")
            or "/data/openneuro/ds000114/bids/sub-01/anat/sub-01_T1w.nii.gz"
        ),
        "subject_id": str(params.get("subject_id") or "sub-01"),
        "output_dir": str(
            params.get("output_dir")
            or "./outputs/out/fastsurfer_single_subject_minimal"
        ),
        "fs_license_file": str(
            params.get("fs_license_file") or "/path/to/freesurfer/license.txt"
        ),
        "n_threads": _coerce_int_value(params.get("n_threads"), 1),
        "use_gpu": bool(params.get("use_gpu", False)),
        "runtime": runtime,
        "container_image": str(
            params.get("container_image")
            or get_container_image("fastsurfer")
            or "deepmi/fastsurfer:latest"
        ),
        "extra_args": extra_args,
        "dry_run": False,
    }


def _build_fmriprep_script(target_runtime: str, payload: dict[str, Any]) -> str:
    command_tokens = [
        "fmriprep" if target_runtime != "container" else "docker",
    ]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "-v",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
                shlex.quote(
                    str(get_container_image("fmriprep") or "nipreps/fmriprep:23.2.3")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$BIDS_DIR"', '"$OUTPUT_DIR"', "participant"])

    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if target_runtime == "container":
        command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
    else:
        command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    if payload["output_spaces"]:
        command_tokens.append("--output-spaces")
        command_tokens.extend(
            shlex.quote(str(space)) for space in payload["output_spaces"]
        )
    command_tokens.extend(["--n-cpus", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(["--mem-mb", str(payload["mem_mb"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
        "",
        'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
        "",
        _render_shell_command(command_tokens),
        "",
    ]
    return "\n".join(lines)


def _build_mriqc_script(target_runtime: str, payload: dict[str, Any]) -> str:
    command_tokens = ["mriqc" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                shlex.quote(
                    str(get_container_image("mriqc") or "nipreps/mriqc:24.0.2")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    else:
        command_tokens.extend(
            [
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    if payload["modalities"]:
        command_tokens.append("--modalities")
        command_tokens.extend(
            shlex.quote(str(modality)) for modality in payload["modalities"]
        )
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    command_tokens.extend(["--n_procs", str(payload["n_procs"])])
    command_tokens.extend(["--mem", f"{int(round(float(payload['mem_gb'])))}G"])
    if payload["bids_filter_file"]:
        command_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
    ]
    if payload["bids_filter_file"]:
        lines.append(
            _render_shell_default("BIDS_FILTER_FILE", str(payload["bids_filter_file"]))
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_qsiprep_script(target_runtime: str, payload: dict[str, Any]) -> str:
    command_tokens = ["qsiprep" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "-v",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
            ]
        )
        if payload["bids_filter_file"]:
            command_tokens.extend(["-v", '"$BIDS_FILTER_FILE:$BIDS_FILTER_FILE:ro"'])
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("qsiprep") or "pennbbl/qsiprep:latest")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    else:
        command_tokens.extend(
            [
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if target_runtime == "container":
        command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
    else:
        command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    if payload["bids_filter_file"]:
        command_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
    command_tokens.extend(["--n_cpus", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(["--mem_mb", str(payload["mem_mb"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
    ]
    if payload["bids_filter_file"]:
        lines.append(
            _render_shell_default("BIDS_FILTER_FILE", str(payload["bids_filter_file"]))
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_smriprep_script(target_runtime: str, payload: dict[str, Any]) -> str:
    command_tokens = ["smriprep" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "-v",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
            ]
        )
        if payload["bids_filter_file"]:
            command_tokens.extend(["-v", '"$BIDS_FILTER_FILE:$BIDS_FILTER_FILE:ro"'])
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("smriprep") or "nipreps/smriprep:0.19.1")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$BIDS_DIR"', '"$OUTPUT_DIR"', "participant"])
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if target_runtime == "container":
        command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
    else:
        command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    if payload["bids_filter_file"]:
        command_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
    command_tokens.extend(["--n-cpus", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(["--mem-mb", str(payload["mem_mb"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
    ]
    if payload["bids_filter_file"]:
        lines.append(
            _render_shell_default("BIDS_FILTER_FILE", str(payload["bids_filter_file"]))
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_qsirecon_script(target_runtime: str, payload: dict[str, Any]) -> str:
    command_tokens = ["qsirecon" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$QSIPREP_DIR:$QSIPREP_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
            ]
        )
        if payload["fs_license_file"]:
            command_tokens.extend(
                ["-v", '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"']
            )
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("qsirecon") or "pennlinc/qsirecon:1.1.1")
                ),
                '"$QSIPREP_DIR"',
                '"$OUTPUT_DIR"',
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$QSIPREP_DIR"', '"$OUTPUT_DIR"', "participant"])
    command_tokens.extend(["--recon-spec", '"$RECON_SPEC"'])
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if payload["fs_license_file"]:
        if target_runtime == "container":
            command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
        else:
            command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    command_tokens.extend(["--nthreads", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("QSIPREP_DIR", str(payload["qsiprep_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default("RECON_SPEC", str(payload["recon_spec"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
    ]
    if payload["fs_license_file"]:
        lines.append(
            'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"'
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_external_repo_bids_recipe(
    tool_id: str,
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    if tool_id == "workflow_fmriprep_preprocessing":
        payload = _minimal_fmriprep_payload(params)
        script_name = "run_workflow_fmriprep_preprocessing.sh"
        script_text = _build_fmriprep_script(
            "container" if target_runtime == "container" else "host", payload
        )
        summary = "single-subject fMRIPrep example with 4 CPUs / 16 GB RAM"
        image_name = "fmriprep"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "A valid FreeSurfer license file is required.",
        ]
    elif tool_id == "workflow_qsiprep":
        payload = _minimal_qsiprep_payload(params)
        script_name = "run_workflow_qsiprep.sh"
        script_text = _build_qsiprep_script(
            "container" if target_runtime == "container" else "host", payload
        )
        summary = "single-subject QSIPrep example with 4 CPUs / 16 GB RAM"
        image_name = "qsiprep"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "A valid FreeSurfer license file is required.",
            "The generated example assumes a diffusion-capable BIDS dataset with DWI inputs.",
        ]
    elif tool_id == "workflow_smriprep":
        payload = _minimal_smriprep_payload(params)
        script_name = "run_workflow_smriprep.sh"
        script_text = _build_smriprep_script("container", payload)
        summary = "single-subject sMRIPrep example with 4 CPUs / 16 GB RAM"
        image_name = "smriprep"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "A valid FreeSurfer license file is required.",
            "The generated local script uses Docker; the Slurm recipe uses Apptainer directly in job.sbatch.",
        ]
    else:
        payload = _minimal_mriqc_payload(params)
        script_name = "run_workflow_mriqc.sh"
        script_text = _build_mriqc_script(
            "container" if target_runtime == "container" else "host", payload
        )
        summary = "single-subject MRIQC example with 4 processes / 8 GB RAM"
        image_name = "mriqc"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile."
        ]

    files = {
        "README.md": _external_repo_recipe_readme(
            tool_id,
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary=summary,
        ),
        script_name: script_text,
        "params.json": _json_text(payload),
    }

    setup_commands: list[str] = []
    run_command = f"bash {script_name}"
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }

    if target_runtime == "neurodesk":
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    elif target_runtime == "container":
        image = str(metadata["container_images"].get(image_name) or "")
        if image:
            setup_commands.append(f"docker pull {image}")
    else:
        if tool_id == "workflow_smriprep":
            image = str(
                metadata["container_images"].get("smriprep")
                or get_container_image("smriprep")
                or "nipreps/smriprep:0.19.1"
            )
            job_tokens = [
                "apptainer",
                "exec",
                "--bind",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "--bind",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "--bind",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "--bind",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
            ]
            if payload["bids_filter_file"]:
                job_tokens.extend(
                    ["--bind", '"$BIDS_FILTER_FILE:$BIDS_FILTER_FILE:ro"']
                )
            job_tokens.extend(
                [
                    f"docker://{image}",
                    "smriprep",
                    '"$BIDS_DIR"',
                    '"$OUTPUT_DIR"',
                    "participant",
                    "--participant-label",
                    '"$PARTICIPANT_LABEL"',
                    "-w",
                    '"$WORK_DIR"',
                    "--fs-license-file",
                    "/opt/freesurfer/license.txt",
                    "--n-cpus",
                    str(payload["n_cpus"]),
                    "--omp-nthreads",
                    str(payload["omp_nthreads"]),
                    "--mem-mb",
                    str(payload["mem_mb"]),
                ]
            )
            if payload["bids_filter_file"]:
                job_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
            job_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])
            job_lines = [
                "#!/bin/bash",
                f"#SBATCH --job-name=br-{_slugify(tool_id)}",
                "#SBATCH --time=24:00:00",
                "#SBATCH --cpus-per-task=4",
                "#SBATCH --mem=16G",
                "#SBATCH --output=slurm-%j.out",
                "#SBATCH --error=slurm-%j.err",
                "",
                "set -euo pipefail",
                "",
                _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
                _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
                _render_shell_default("WORK_DIR", str(payload["work_dir"])),
                _render_shell_default(
                    "PARTICIPANT_LABEL", str(payload["participant_label"][0])
                ),
                'FS_LICENSE_FILE="${FS_LICENSE:-'
                + str(payload["fs_license_file"])
                + '}"',
            ]
            if payload["bids_filter_file"]:
                job_lines.append(
                    _render_shell_default(
                        "BIDS_FILTER_FILE", str(payload["bids_filter_file"])
                    )
                )
            job_lines.extend(
                [
                    "",
                    'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
                    "",
                    _render_shell_command(job_tokens),
                    "",
                ]
            )
            files["job.sbatch"] = "\n".join(job_lines)
        else:
            module_lines = [
                f"module load {module}" for module in metadata["neurodesk_modules"]
            ]
            env_lines = _env_exports(metadata["required_env_vars"])
            if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
                rendered = sherlock_render_sbatch_script(
                    "cpu_single",
                    cluster_profile=cluster_profile,
                    job_name=f"br-{_slugify(tool_id)}",
                    module_lines=module_lines or None,
                    env_lines=env_lines or None,
                    command=f"bash {script_name}",
                )
                files["job.sbatch"] = str(rendered.get("script_text") or "")
            else:
                lines = [
                    "#!/bin/bash",
                    f"#SBATCH --job-name=br-{_slugify(tool_id)}",
                    "#SBATCH --time=24:00:00",
                    "#SBATCH --cpus-per-task=4",
                    "#SBATCH --mem=16G",
                    "#SBATCH --output=slurm-%j.out",
                    "#SBATCH --error=slurm-%j.err",
                    "",
                    "set -euo pipefail",
                    "",
                    *module_lines,
                    *env_lines,
                    f"bash {script_name}",
                    "",
                ]
                files["job.sbatch"] = "\n".join(lines)
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": warnings,
    }
    return recipe, "runnable"


def _build_qsirecon_minimal_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    payload = _minimal_qsirecon_payload(params)
    script_name = "run_workflow_qsirecon.sh"
    script_text = _build_qsirecon_script(
        "container" if target_runtime == "container" else "host", payload
    )
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_qsirecon",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary="single-subject QSIRecon example with 4 CPUs / 16 GB RAM",
        ),
        script_name: script_text,
        "params.json": _json_text(payload),
    }
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"bash {script_name}"
    if target_runtime == "container":
        image = str(
            metadata["container_images"].get("qsirecon")
            or get_container_image("qsirecon")
            or "pennlinc/qsirecon:1.1.1"
        )
        setup_commands.append(f"docker pull {image}")
    else:
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow_qsirecon",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"bash {script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            lines = [
                "#!/bin/bash",
                "#SBATCH --job-name=br-workflow_qsirecon",
                "#SBATCH --time=24:00:00",
                "#SBATCH --cpus-per-task=4",
                "#SBATCH --mem=16G",
                "#SBATCH --output=slurm-%j.out",
                "#SBATCH --error=slurm-%j.err",
                "",
                "set -euo pipefail",
                "",
                *module_lines,
                *env_lines,
                f"bash {script_name}",
                "",
            ]
            files["job.sbatch"] = "\n".join(lines)
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "Provide a QSIPrep derivative root produced by workflow_qsiprep or an equivalent official QSIPrep run.",
            "Keep recon_spec on a known preset when promoting recipes to stable workflow packs.",
        ],
    }
    return recipe, "runnable"


def _build_fastsurfer_minimal_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    payload = _minimal_fastsurfer_payload(params)
    script_name = "run_workflow_fastsurfer.sh"
    image = str(
        payload["container_image"]
        or metadata["container_images"].get("fastsurfer")
        or "deepmi/fastsurfer:latest"
    )
    device = "cuda" if payload["use_gpu"] else "cpu"
    command_tokens = [
        "docker",
        "run",
        "--rm",
        "-v",
        '"$T1W_IMAGE:/input/t1w.nii.gz:ro"',
        "-v",
        '"$OUTPUT_DIR:/out:rw"',
        "-v",
        '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
        shlex.quote(image),
        "run_fastsurfer.sh",
        "--sid",
        '"$SUBJECT_ID"',
        "--sd",
        "/out",
        "--t1",
        "/input/t1w.nii.gz",
        "--threads",
        '"$N_THREADS"',
        "--device",
        device,
        "--fs_license",
        "/opt/freesurfer/license.txt",
    ]
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    script_text = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            _render_shell_default("T1W_IMAGE", str(payload["t1w_image"])),
            _render_shell_default("SUBJECT_ID", str(payload["subject_id"])),
            _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
            _render_shell_default("N_THREADS", str(payload["n_threads"])),
            'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
            "",
            'mkdir -p "$OUTPUT_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "container_images": metadata["container_images"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [f"docker pull {image}"],
        "run_command": f"bash {script_name}",
        "params_json": _json_text(payload),
        "files": {
            "README.md": _external_repo_recipe_readme(
                "workflow_fastsurfer",
                target_runtime=target_runtime,
                metadata=metadata,
                script_name=script_name,
                minimal_summary="single-subject FastSurfer example with 1 CPU thread",
            ),
            script_name: script_text,
            "params.json": _json_text(payload),
        },
        "warnings": [
            "The generated FastSurfer recipe uses Docker for the minimal execution path even though the BR workflow default runtime is apptainer.",
            "A valid FreeSurfer license file is required.",
        ],
    }
    return recipe, "runnable"


def build_execution_recipe(
    tool_id: str,
    *,
    params: dict[str, Any] | None = None,
    target_runtime: str,
    cluster_profile: str = DEFAULT_CLUSTER_PROFILE,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = _merge_workflow_default_params(dict(params or {}), workflow_entry)
    normalized_target = normalize_recipe_target(target_runtime)
    auto_target = str(target_runtime or "").strip().lower() in AUTO_RECIPE_TARGETS
    requested_tool_id = str(tool_id or "").strip()
    lookup_tool_id = _recipe_lookup_tool_id(requested_tool_id)
    spec_tool_id = (
        str(spec.name).strip() if spec is not None and str(spec.name).strip() else ""
    )
    execution_tool_id = (
        resolve_primary_runtime_tool_id(spec_tool_id or lookup_tool_id)
        or spec_tool_id
        or lookup_tool_id
    )
    if not auto_target and normalized_target not in RECIPE_TARGETS:
        return {
            "ok": False,
            "requested_tool_id": requested_tool_id,
            "resolved_tool_id": execution_tool_id or tool_id,
            "target_runtime": normalized_target,
            "cluster_profile": cluster_profile,
            "hosted_via_br_mcp_service": False,
            "supported_recipe_targets": [],
            "recipe_depth": "summary",
            "warnings": [],
            "unsupported_reason": f"Unsupported target_runtime: {target_runtime}",
            "error": "unsupported_recipe_target",
        }

    requested_metadata = resolve_recipe_metadata(
        requested_tool_id,
        spec=spec,
        workflow_entry=workflow_entry,
    )
    recipe_tool_id = (
        execution_tool_id
        if (lookup_tool_id != requested_tool_id or spec_tool_id)
        else requested_tool_id
    )
    metadata = requested_metadata
    if not requested_metadata.get("known_recipe_subject"):
        metadata = resolve_recipe_metadata(execution_tool_id, spec=spec)
        recipe_tool_id = execution_tool_id
    supported_targets = metadata["supported_recipe_targets"]
    execution_story = metadata["execution_story"]
    execution_story_kind = metadata["execution_story_kind"]
    if auto_target:
        normalized_target = normalize_recipe_target(metadata["primary_target"])
        if not normalized_target and supported_targets:
            normalized_target = supported_targets[0]
        if not normalized_target:
            normalized_target = "python"
    if not supported_targets:
        return {
            "ok": True,
            "requested_tool_id": requested_tool_id,
            "resolved_tool_id": execution_tool_id or tool_id,
            "target_runtime": normalized_target,
            "cluster_profile": cluster_profile,
            "execution_story_kind": execution_story_kind,
            "hosted_via_br_mcp_service": metadata["hosted_via_br_mcp_service"],
            "execution_story": execution_story,
            "supported_recipe_targets": supported_targets,
            "recipe_depth": "summary",
            "recipe": None,
            "warnings": [],
            "unsupported_reason": None,
            **_recipe_subject_metadata(metadata),
            **agent_execution_metadata(
                metadata,
                requested_target=normalized_target,
                recipe_available=False,
            ),
        }
    if normalized_target not in supported_targets:
        return {
            "ok": False,
            "requested_tool_id": requested_tool_id,
            "resolved_tool_id": execution_tool_id or tool_id,
            "target_runtime": normalized_target,
            "cluster_profile": cluster_profile,
            "execution_story_kind": execution_story_kind,
            "hosted_via_br_mcp_service": metadata["hosted_via_br_mcp_service"],
            "execution_story": execution_story,
            "supported_recipe_targets": supported_targets,
            "recipe_depth": metadata["recipe_depth"],
            "warnings": [],
            "unsupported_reason": (
                f"'{execution_tool_id or requested_tool_id}' does not advertise a '{normalized_target}' recipe. "
                f"Supported targets: {supported_targets}"
            ),
            "error": "unsupported_recipe_target",
            **_recipe_subject_metadata(metadata),
            **agent_execution_metadata(
                metadata,
                requested_target=normalized_target,
                recipe_available=False,
            ),
        }

    if (
        execution_tool_id == "workflow_rest_connectome_e2e"
        and normalized_target == "python"
    ):
        recipe, depth = _build_rest_connectome_python_recipe(
            params,
            metadata,
            spec=spec,
            workflow_entry=workflow_entry,
        )
    elif execution_tool_id in {
        "workflow_fmriprep_preprocessing",
        "workflow_mriqc",
        "workflow_qsiprep",
        "workflow_smriprep",
    } and normalized_target in {"neurodesk", "container", "slurm"}:
        recipe, depth = _build_external_repo_bids_recipe(
            execution_tool_id,
            normalized_target,
            params,
            metadata,
            cluster_profile=cluster_profile,
        )
    elif execution_tool_id == "workflow_qsirecon" and normalized_target in {
        "container",
        "slurm",
    }:
        recipe, depth = _build_qsirecon_minimal_recipe(
            normalized_target,
            params,
            metadata,
            cluster_profile=cluster_profile,
        )
    elif (
        execution_tool_id == "workflow_fastsurfer" and normalized_target == "container"
    ):
        recipe, depth = _build_fastsurfer_minimal_recipe(
            normalized_target,
            params,
            metadata,
        )
    elif execution_tool_id == "workflow_preprocessing_qc" and normalized_target in {
        "neurodesk",
        "container",
        "slurm",
    }:
        recipe, depth = _build_preprocessing_qc_recipe(
            normalized_target,
            params,
            metadata,
            cluster_profile=cluster_profile,
        )
    elif execution_tool_id == "workflow_task_glm_group" and normalized_target in {
        "neurodesk",
        "container",
        "slurm",
    }:
        recipe, depth = _build_task_glm_group_recipe(
            normalized_target,
            params,
            metadata,
            cluster_profile=cluster_profile,
        )
    elif execution_tool_id == "workflow_dwi_connectome" and normalized_target in {
        "neurodesk",
        "container",
        "slurm",
    }:
        recipe, depth = _build_dwi_connectome_recipe(
            normalized_target,
            params,
            metadata,
            cluster_profile=cluster_profile,
        )
    elif (
        normalized_target == "python"
        and str(metadata.get("recipe_family") or "").strip()
        in _DIRECT_PYTHON_RECIPE_FAMILIES
    ):
        recipe, depth = _build_direct_family_python_recipe(
            recipe_tool_id,
            params,
            metadata,
            spec=spec,
            workflow_entry=workflow_entry,
        )
    elif normalized_target == "python":
        recipe, depth = _build_generic_python_recipe(
            recipe_tool_id,
            params,
            metadata,
            spec=spec,
            workflow_entry=workflow_entry,
        )
    elif normalized_target == "neurodesk":
        recipe, depth = _build_generic_neurodesk_recipe(
            recipe_tool_id, params, metadata
        )
    elif normalized_target == "container":
        recipe, depth = _build_generic_container_recipe(
            recipe_tool_id, params, metadata
        )
    else:
        recipe, depth = _build_generic_slurm_recipe(
            recipe_tool_id,
            params,
            metadata,
            cluster_profile=cluster_profile,
        )

    run_pack = _recipe_run_pack_payload(recipe_tool_id, normalized_target, recipe)
    return {
        "ok": True,
        "requested_tool_id": requested_tool_id,
        "resolved_tool_id": execution_tool_id or tool_id,
        "target_runtime": normalized_target,
        "cluster_profile": cluster_profile,
        "execution_story_kind": execution_story_kind,
        "hosted_via_br_mcp_service": metadata["hosted_via_br_mcp_service"],
        "execution_story": execution_story,
        "supported_recipe_targets": supported_targets,
        "recipe_depth": depth,
        "recipe": recipe,
        "run_pack": run_pack,
        "local_run": run_pack,
        "warnings": recipe.get("warnings", []),
        "unsupported_reason": None,
        **_recipe_subject_metadata(metadata),
        **agent_execution_metadata(
            metadata,
            requested_target=normalized_target,
            recipe_available=True,
        ),
    }


def default_recipe_target(
    tool_id: str,
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> str | None:
    metadata = resolve_recipe_metadata(
        tool_id, spec=spec, workflow_entry=workflow_entry
    )
    primary = normalize_recipe_target(metadata["primary_target"])
    return primary or None


__all__ = [
    "AUTO_RECIPE_TARGETS",
    "DEFAULT_CLUSTER_PROFILE",
    "RECIPE_TARGETS",
    "agent_execution_metadata",
    "build_execution_recipe",
    "default_recipe_target",
    "is_first_wave_heavy_runtime_workflow",
    "is_long_running_batch_analysis_workflow",
    "is_recipe_first_mcp_workflow",
    "materialize_execution_pack",
    "materialize_recipe_files",
    "normalize_recipe_target",
    "recipe_card_metadata",
    "resolve_recipe_metadata",
]
