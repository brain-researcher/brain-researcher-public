"""Recipe inference helpers for public MCP tool recipes.

Carved out of ``mcp/execution_recipes.py``: the helpers that INFER recipe
properties — supported targets, neurodesk modules, python packages (incl. the
direct-family package set), required env vars, resource profile, execution-story
kind, and the neurodesk package-profile resolution. The shared lower-level
helpers they use stay in ``execution_recipes`` and are imported back lazily, so
this module imports nothing from ``execution_recipes`` at load (cycle-free).
``execution_recipes`` re-exports these so ``resolve_recipe_metadata`` and the
``_neurodesk_module_resolution`` back-reference keep resolving.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
)
from brain_researcher.services.tools.runtime_profiles import (
    get_container_image,
    get_neurodesk_package_profile,
    normalize_runtime_package_name,
)
from brain_researcher.services.tools.spec import (
    ToolExecutionCapabilities,
    ToolSpec,
    infer_requires_runtime,
)


def _resolve_neurodesk_package_profile(tool_id: str) -> dict[str, Any] | None:
    from brain_researcher.services.tools.execution_recipes import (
        _NEURODESK_PREFIX_MAP,
        _recipe_lookup_tool_id,
    )

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


def _infer_supported_targets(
    tool_id: str,
    *,
    spec: ToolSpec | None,
    workflow_entry: dict[str, Any] | None,
) -> list[str]:
    from brain_researcher.services.tools.execution_recipes import (
        _BIDS_APPS,
        _HOSTED_TOOL_IDS,
        _NEURODESK_PREFIX_MAP,
        _dedupe,
        _workflow_recipe_analysis,
        _workflow_uses_bids_apps,
    )

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
    from brain_researcher.services.tools.execution_recipes import (
        _dedupe,
        _neurodesk_module_resolution,
        _step_tools,
        _workflow_uses_bids_apps,
    )

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
    from brain_researcher.services.tools.execution_recipes import _dedupe

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
    from brain_researcher.services.tools.execution_recipes import (
        _dedupe,
        _normalize_list,
        _workflow_uses_bids_apps,
    )

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
    from brain_researcher.services.tools.execution_recipes import _normalize_dict

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
    from brain_researcher.services.tools.execution_recipes import (
        _HOSTED_TOOL_IDS,
        _NEURODESK_PREFIX_MAP,
        EXECUTION_STORY_KINDS,
        _workflow_recipe_analysis,
    )

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
