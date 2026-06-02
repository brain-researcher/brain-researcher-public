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

from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)

# Per-workflow recipe/script builders were carved into recipe_builders.py.
# Re-exported so the build_execution_recipe dispatcher (which calls them) and any
# importers keep resolving. recipe_builders imports nothing from this module at
# load (lazy import-backs) → cycle-free.
from brain_researcher.services.tools.recipe_builders import (  # noqa: F401,E402
    _build_direct_family_python_recipe,
    _build_dwi_connectome_postprocess_script,
    _build_dwi_connectome_recipe,
    _build_dwi_connectome_runner_script,
    _build_dwi_connectome_script,
    _build_external_repo_bids_recipe,
    _build_fastsurfer_minimal_recipe,
    _build_fmriprep_script,
    _build_generic_container_recipe,
    _build_generic_neurodesk_recipe,
    _build_generic_python_recipe,
    _build_generic_slurm_recipe,
    _build_mriqc_script,
    _build_preprocessing_qc_recipe,
    _build_qsiprep_script,
    _build_qsirecon_minimal_recipe,
    _build_qsirecon_script,
    _build_rest_connectome_python_recipe,
    _build_smriprep_script,
    _build_task_glm_group_recipe,
)

# Recipe inference helpers were carved into recipe_inference.py (re-exported so
# resolve_recipe_metadata + the _neurodesk_module_resolution back-ref resolve).
from brain_researcher.services.tools.recipe_inference import (  # noqa: F401,E402
    _direct_family_python_packages,
    _infer_execution_story_kind,
    _infer_neurodesk_modules,
    _infer_python_packages,
    _infer_required_env_vars,
    _infer_resource_profile,
    _infer_supported_targets,
    _resolve_neurodesk_package_profile,
)

# Python execution-pack assembly was carved into recipe_pack.py (re-exported).
from brain_researcher.services.tools.recipe_pack import (  # noqa: F401,E402
    _attach_python_pack_contract,
    _base_python_pack_manifest,
    _embedded_python_pack_manifest,
    _generated_python_pack_runner,
    _local_tool_pack_manifest,
    _pack_confounds_policy,
    _pack_handoff,
    _pack_input_bindings,
    _recipe_run_pack_payload,
    _run_pack_environment,
    _run_pack_prerequisites,
)

# Minimal recipe payloads were carved into recipe_payloads.py (re-exported so
# recipe_builders + the dispatcher keep resolving them).
from brain_researcher.services.tools.recipe_payloads import (  # noqa: F401,E402
    _minimal_dwi_connectome_payload,
    _minimal_fastsurfer_payload,
    _minimal_fmriprep_payload,
    _minimal_mriqc_payload,
    _minimal_preprocessing_qc_payload,
    _minimal_qsiprep_payload,
    _minimal_qsirecon_payload,
    _minimal_smriprep_payload,
    _minimal_task_glm_group_payload,
)

# Per-analysis script generators were carved into recipe_scripts.py (re-exported
# so recipe_builders + importers keep resolving them).
from brain_researcher.services.tools.recipe_scripts import (  # noqa: F401,E402
    _connectivity_matrix_python_script,
    _default_runtime_script,
    _direct_python_script_for_family,
    _encoding_models_python_script,
    _glm_first_level_python_script,
    _glm_second_level_python_script,
    _mvpa_python_script,
    _preprocessing_container_script,
    _preprocessing_neurodesk_script,
    _preprocessing_post_qc_script,
    _rest_connectome_python_script,
    _searchlight_python_script,
    _seed_based_connectivity_python_script,
    _temporal_decoding_python_script,
)
from brain_researcher.services.tools.runtime_profiles import (
    execution_recipe_config_path,
    get_container_image,
    get_tool_recipe_declaration,
    get_tool_recipe_override,
)
from brain_researcher.services.tools.spec import (
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
    "br_kg.client",
    "br_kg.detect_contradiction_motifs",
    "br_kg.detect_topology_shifts",
    "br_kg.find_structural_leverage",
    "br_kg.sample_ood_hypothesis",
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


def _parse_module_ref(module_ref: str) -> tuple[str, str]:
    """Split a neurodesk module string ("fmriprep/23.2.3") into (name, version)."""

    text = str(module_ref or "").strip()
    if "/" in text:
        name, _, version = text.partition("/")
        return name.strip(), version.strip()
    return text, ""


def _augment_module_summary_from_recipe(
    module_resolution: dict[str, Any],
    *,
    neurodesk_modules: list[str],
    container_images: dict[str, Any],
) -> dict[str, Any]:
    """Surface the real pinned version into the neurodesk_* summary fields.

    Wrapper-backed workflows (e.g. ``workflow_fmriprep_preprocessing``) have an
    empty neurodesk package profile, so the pin (``fmriprep/23.2.3`` /
    ``nipreps/fmriprep:23.2.3``) only lives inside ``recipe.dependencies``. A
    client reading the summary fields ``neurodesk_recommended_version`` /
    ``neurodesk_available_modules`` would otherwise see ``null``/``[]`` and miss
    it. Backfill those summary fields from the concrete recipe modules/images
    without overriding an authoritative package profile.
    """

    resolved = dict(module_resolution or {})
    if resolved.get("neurodesk_recommended_version"):
        return resolved
    if not neurodesk_modules and not container_images:
        return resolved

    parsed = [_parse_module_ref(module) for module in neurodesk_modules]
    parsed = [(name, version) for (name, version) in parsed if name]

    image_keys = {str(key).strip().lower() for key in (container_images or {})}

    def _is_primary(name: str) -> bool:
        low = name.strip().lower()
        return low in image_keys or low in _BIDS_APPS

    primary = next((item for item in parsed if _is_primary(item[0])), None)
    if primary is None and parsed:
        primary = parsed[0]

    if primary is not None:
        name, version = primary
        resolved.setdefault("neurodesk_package_name", name.lower())
        resolved.setdefault("neurodesk_module_name", name)
        if version:
            resolved["neurodesk_recommended_version"] = version
        resolved["neurodesk_recommended_module"] = (
            f"{name}/{version}" if version else name
        )

    available_modules = [
        f"{name}/{version}" if version else name for (name, version) in parsed
    ]
    if available_modules and not resolved.get("neurodesk_available_modules"):
        resolved["neurodesk_available_modules"] = available_modules
    available_versions = [version for (_name, version) in parsed if version]
    if available_versions and not resolved.get("neurodesk_available_versions"):
        resolved["neurodesk_available_versions"] = available_versions

    # Fall back to a container image tag ("nipreps/fmriprep:23.2.3" -> "23.2.3")
    # when no neurodesk module carried a version.
    if not resolved.get("neurodesk_recommended_version") and container_images:
        for app, image in container_images.items():
            _, sep, tag = str(image or "").rpartition(":")
            tag = tag.strip()
            if sep and tag and "/" not in tag:
                resolved["neurodesk_recommended_version"] = tag
                resolved.setdefault("neurodesk_module_name", str(app))
                resolved.setdefault("neurodesk_package_name", str(app).lower())
                if not resolved.get("neurodesk_available_versions"):
                    resolved["neurodesk_available_versions"] = [tag]
                break

    return resolved


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


def _recipe_local_run_payload(
    tool_id: str,
    target_runtime: str,
    recipe: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _recipe_run_pack_payload(tool_id, target_runtime, recipe)


def _local_run_alias_payload(run_pack: dict[str, Any] | None) -> dict[str, Any] | None:
    if run_pack is None:
        return None
    return {
        "alias_for": "run_pack",
        "ref": "#/run_pack",
        "deprecated": True,
        "message": (
            "local_run is a compact backwards-compatible alias. Use run_pack, "
            "or call get_execution_recipe(..., include_legacy_local_run=True) "
            "for the legacy duplicated payload."
        ),
    }


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

    # Surface the pin from recipe.dependencies into the neurodesk_* summary fields
    # when the package profile is empty (wrapper-backed workflows).
    module_resolution = _augment_module_summary_from_recipe(
        module_resolution,
        neurodesk_modules=neurodesk_modules,
        container_images=container_images,
    )

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
    return (
        dedent(
            f"""
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
        """
        ).strip()
        + "\n"
    )


def build_execution_recipe(
    tool_id: str,
    *,
    params: dict[str, Any] | None = None,
    target_runtime: str,
    cluster_profile: str = DEFAULT_CLUSTER_PROFILE,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
    include_legacy_local_run: bool = False,
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
    local_run = (
        run_pack if include_legacy_local_run else _local_run_alias_payload(run_pack)
    )
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
        "local_run": local_run,
        "local_run_alias": not include_legacy_local_run and run_pack is not None,
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
