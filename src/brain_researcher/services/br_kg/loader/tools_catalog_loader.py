"""Ingest tools from the catalog into BR-KG.

This loader is intentionally lightweight and idempotent. It parses the
capabilities YAML and maps each tool into Tool/ToolVersion nodes plus
relationships for resources (consumes/produces), modalities, and
capability families. Optional evidence data (publications, validated
collections) can also be attached.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import get_config_root
from brain_researcher.services.shared.planner.models import ResourceType

logger = logging.getLogger(__name__)

_EXPOSED_ALIAS_MAP: dict[str, str] = {
    "datasets.list_resources": "datasets.list_resources",
    "datasets.describe_resources": "datasets.describe_resources",
    "fmri.connectivity_client.light": "connectivity_matrix",
    "extract_timeseries": "python.extract_timeseries.run",
    "fetch_atlas": "python.fetch_atlas.run",
    "fsl_fast": "fsl.6.0.4.fast.run",
    "fsl_prepare_fieldmap": "fsl.6.0.4.fsl_prepare_fieldmap.run",
    "fsl_topup": "fsl.6.0.4.topup.run",
    "fsl_epi_reg": "fsl.6.0.4.epi_reg.run",
}

_LOCAL_FIRST_ALLOWED_EXACT: set[str] = {
    tool_id.lower()
    for tool_id in {
        "datasets.client",
        "datasets.describe_resources",
        "datasets.list_resources",
        "gemini.fs",
        "gemini.net",
        "hypothesis_hot_load_research",
        "hypothesis_run_get",
        "hypothesis_run_start",
        "kg_multihop_qa",
        "kg_hypothesis_candidate_cards",
        "kg_hypothesis_candidate_cards_get",
        "kg_hypothesis_candidate_cards_start",
        "mcp.server_info",
        "mcp.system_self_test",
        "mcp.sherlock_guide",
        "mcp.sherlock_slurm",
        "mcp.tool_search",
        "br_kg.client",
        "niwrap_schema",
        "niwrap_search",
        "workflow_rest_connectome_e2e",
        "fetch_atlas",
        "extract_timeseries",
        "compute_connectivity",
        "connectivity_matrix",
        "spm12_vbm",
        "workflow_realtime_twophoton_closed_loop",
        "workflow_realtime_twophoton_file_replay",
    }
}

_LOCAL_FIRST_BLOCKED_EXACT: set[str] = {
    tool_id.lower()
    for tool_id in {
        "bidsapp.fmriprep.run",
        "bidsapp.mriqc.run",
        "bidsapp.qsiprep.run",
        "bidsapp.xcpd.run",
        "container.fitlins.recipe.run",
        "fitlins.recipe.run",
        "niwrap_execute",
        "tool_execute",
        "pipeline_execute",
        "python.fmriprep.run",
        "python.mriqc.run",
        "python.qsiprep.run",
        "run_local_script",
        "code_agent",
        "code.agent.run",
        "gemini.run_shell",
        "run_bids_app",
        "run_fitlins_recipe",
        "run_fmriprep",
        "run_mriqc",
        "run_mriqc_workflow",
        "run_qsiprep",
        "run_searchlight",
        "run_aslprep",
        "run_glm_second_level",
        "run_tractography",
        "run_xcp_d",
        "glm_multiverse",
        "glm_multiverse.run",
        "fsl.melodic",
        "fsl.fslFixText",
        "afni.3dClustSim",
        "fetch_atlas",
        "extract_timeseries",
        "compute_connectivity",
        "connectivity_matrix",
        "openneuro_download",
        "dandi_download",
        "prefetch.openneuro_cache",
        "neurodesk_command",
        "fsl_command",
        "mrtrix3_command",
        "mrtrix.3.0.4.dwi2fod.run",
        "diffusion_tractography",
        "validate_bids",
        "derivatives_sanity_checker",
        "cross_validation",
        "ml_cross_validation",
        "validation_metrics",
    }
}

_LOCAL_FIRST_BLOCKED_PREFIXES: tuple[str, ...] = (
    "container.bidsapp.",
    "bidsapp.",
    "fmriprep_",
    "fsl.",
    "fsl_",
    "afni.",
    "afni_",
    "ants.",
    "ants_",
    "mrtrix.",
    "mrtrix3.",
    "mrtrix3_",
    "freesurfer_",
    "python.fmriprep.",
    "python.mriqc.",
    "python.qsiprep.",
    "python.xcpd.",
    "qsiprep_",
    "run_",
    "workflow_",
    "xcpd_",
)

CATEGORY_TO_KIND: dict[str, str] = {
    "knowledge_graph": "kg",
    "meta_analysis": "meta",
    "visualization": "viz",
    "preprocessing": "imaging",
    "registration": "imaging",
    "segmentation": "imaging",
    "statistical_analysis": "analysis",
    "connectivity": "analysis",
    "diffusion": "imaging",
    "surface": "imaging",
    "machine_learning": "analysis",
    "deep_learning": "analysis",
    "electrophysiology": "analysis",
    "data_management": "data",
    "quality_control": "imaging",
    "statistical_inference": "analysis",
    "clinical": "imaging",
    "realtime": "imaging",
    "simulation": "analysis",
    "workflow": "analysis",
    "feature_selection": "analysis",
    "advanced_analysis": "analysis",
    "data_harmonization": "data",
    "specialized_processing": "imaging",
}


@dataclass(frozen=True)
class ToolCatalogRecord:
    """Small BR-KG catalog record used for tool search fallbacks."""

    name: str
    description: str | None
    category: str | None
    intents: tuple[str, ...]


def _resolve_configs_dir() -> Path:
    """Resolve repo-level configs directory relative to this module."""
    path = Path(__file__).resolve()
    for parent in path.parents:
        candidate = parent / "configs"
        if candidate.exists():
            return candidate
    return get_config_root()


CONFIGS_DIR = _resolve_configs_dir()


def _normalize_id_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not value:
            continue
        tool_id = str(value).strip()
        if not tool_id or tool_id in seen:
            continue
        items.append(tool_id)
        seen.add(tool_id)
    return items


def _allow_remote_execution_tools() -> bool:
    import os

    return os.environ.get(
        "BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS",
        "",
    ).strip().lower() in {"1", "true", "yes", "on"}


def _is_local_first_blocked_tool(tool_id: str) -> bool:
    normalized = str(tool_id or "").strip()
    if not normalized or _allow_remote_execution_tools():
        return False
    lowered = normalized.lower()
    if lowered in _LOCAL_FIRST_ALLOWED_EXACT:
        return False
    if lowered in _LOCAL_FIRST_BLOCKED_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in _LOCAL_FIRST_BLOCKED_PREFIXES)


def _filter_agent_visible_tool_ids(tool_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        normalized = str(tool_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if _is_local_first_blocked_tool(normalized):
            continue
        out.append(normalized)
    return out


def _normalize_mapping_targets(raw: Any) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return normalized

    for key, value in raw.items():
        key_str = str(key or "").strip()
        if not key_str:
            continue
        if isinstance(value, list):
            raw_targets = value
        elif value is None:
            raw_targets = []
        else:
            raw_targets = [value]

        targets: list[str] = []
        seen: set[str] = set()
        for item in raw_targets:
            item_str = str(item or "").strip()
            if not item_str or item_str in seen:
                continue
            targets.append(item_str)
            seen.add(item_str)
        normalized[key_str] = targets

    return normalized


@lru_cache(maxsize=1)
def load_tool_id_mappings() -> dict[str, dict[str, list[str]]]:
    """Load catalog/runtime ID mappings needed for BR-KG tool metadata."""

    path = resolve_mapping_path(
        "tool_id_mappings",
        fallback=CONFIGS_DIR / "catalog" / "tool_id_mappings.yaml",
        must_exist=False,
    )
    if not path.exists():
        return {"catalog_to_runtime": {}, "runtime_to_catalog": {}}

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        logger.warning("Failed to load tool_id_mappings.yaml: %s", exc)
        return {"catalog_to_runtime": {}, "runtime_to_catalog": {}}

    catalog_to_runtime = _normalize_mapping_targets(data.get("catalog_to_runtime"))
    runtime_to_catalog = _normalize_mapping_targets(data.get("runtime_to_catalog"))

    if not runtime_to_catalog and catalog_to_runtime:
        for catalog_id, runtime_ids in catalog_to_runtime.items():
            for runtime_id in runtime_ids:
                runtime_to_catalog.setdefault(runtime_id, []).append(catalog_id)

    return {
        "catalog_to_runtime": catalog_to_runtime,
        "runtime_to_catalog": runtime_to_catalog,
    }


def get_exposed_alias_map() -> dict[str, str]:
    """Return a copy of exposed-tool alias mapping."""

    return dict(_EXPOSED_ALIAS_MAP)


def resolve_catalog_tool_id(
    tool_id: str,
    *,
    exposed_only: bool,
    alias_map: dict[str, str] | None = None,
) -> str:
    """Resolve exposed aliases to catalog IDs for catalog-backed records."""

    if not exposed_only:
        return tool_id
    aliases = alias_map if isinstance(alias_map, dict) else _EXPOSED_ALIAS_MAP
    return aliases.get(tool_id, tool_id)


@lru_cache(maxsize=2)
def load_exposed_tools(*, agent_visible_only: bool = True) -> list[str]:
    """Load the curated exposed tool list for BR-KG catalog fallback paths."""

    gm_path = CONFIGS_DIR / "grandmaster" / "toolset_vfinal.yaml"
    if gm_path.exists():
        try:
            data = yaml.safe_load(gm_path.read_text()) or {}
            exposure = data.get("exposure") if isinstance(data, dict) else None
            if isinstance(exposure, dict):
                exposed = _normalize_id_list(exposure.get("exposed"))
                if agent_visible_only:
                    exposed = _filter_agent_visible_tool_ids(exposed)
                if exposed:
                    return exposed
        except Exception as exc:
            logger.warning("Failed to load grandmaster exposure list: %s", exc)

    legacy_path = CONFIGS_DIR / "catalog" / "exposed_tools.yaml"
    if not legacy_path.exists():
        logger.warning("Exposed tools whitelist not found at %s", legacy_path)
        return []

    try:
        data = yaml.safe_load(legacy_path.read_text()) or {}
        exposed = _normalize_id_list(
            data.get("exposed") if isinstance(data, dict) else None
        )
        if agent_visible_only:
            exposed = _filter_agent_visible_tool_ids(exposed)
        if exposed:
            return exposed
    except Exception as exc:
        logger.warning("Failed to load legacy exposed tools list: %s", exc)
    return []


@lru_cache(maxsize=1)
def load_tools_catalog() -> dict[str, dict[str, Any]]:
    """Load tools_catalog_merged.json with tracked BR tool overrides."""

    path = CONFIGS_DIR / "tools_catalog_merged.json"
    if not path.exists():
        logger.warning("Tools catalog not found at %s", path)
        data: dict[str, Any] = {}
    else:
        with path.open("r") as f:
            data = json.load(f)

    merged: dict[str, dict[str, Any]] = {
        t["name"]: t
        for t in data.get("tools", [])
        if isinstance(t, dict) and t.get("name")
    }

    overrides_path = CONFIGS_DIR / "tools_catalog_overrides.yaml"
    if overrides_path.exists():
        try:
            overrides_raw = yaml.safe_load(overrides_path.read_text()) or {}
            tools_raw = overrides_raw.get(
                "tools",
                overrides_raw if isinstance(overrides_raw, list) else [],
            )
            if isinstance(tools_raw, list):
                for entry in tools_raw:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name")
                    if name:
                        key = str(name)
                        if isinstance(merged.get(key), dict):
                            merged[key].update(entry)
                        else:
                            merged[key] = entry
        except Exception as exc:
            logger.warning("Failed to load tools_catalog_overrides.yaml: %s", exc)

    return merged


@lru_cache(maxsize=1)
def load_categories() -> dict[str, Any]:
    """Load tool_categories.yaml."""

    path = CONFIGS_DIR / "tool_categories.yaml"
    if not path.exists():
        logger.warning("Tool categories not found at %s", path)
        return {}

    with path.open("r") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_niwrap_mapping() -> dict[str, Any]:
    """Load niwrap_mapping.yaml for modalities/intents."""

    path = resolve_mapping_path(
        "niwrap_mapping",
        fallback=CONFIGS_DIR / "catalog" / "niwrap_mapping.yaml",
        must_exist=False,
    )
    if not path.exists():
        logger.warning("NiWrap mapping not found at %s", path)
        return {}

    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def resolve_category(tool_id: str, categories_config: dict[str, Any]) -> str | None:
    """Resolve category for a tool using exact matches and pattern rules."""

    exact_matches = categories_config.get("pattern_matching", {}).get(
        "exact_matches",
        {},
    )
    if tool_id in exact_matches:
        return exact_matches[tool_id]

    pattern_rules = categories_config.get("pattern_matching", {}).get(
        "pattern_rules",
        [],
    )
    for rule in pattern_rules:
        pattern = rule.get("pattern", "")
        if pattern and re.match(pattern, tool_id, re.IGNORECASE):
            return rule.get("category")

    return categories_config.get("default_category", "unknown")


def resolve_niwrap_metadata(
    tool_id: str,
    package: str,
    niwrap_map: dict[str, Any],
) -> tuple[list[str], list[str], str | None]:
    """Resolve modalities, intents, and niwrap_id from niwrap_mapping.yaml."""

    defaults = niwrap_map.get("default", {})
    default_modalities = defaults.get("modalities", ["fmri", "smri", "dmri"])
    default_intents = defaults.get("default_intents", ["generic_container_op"])

    packages = niwrap_map.get("packages", {})
    pkg_config = packages.get(package, {})

    modalities = pkg_config.get("modalities", default_modalities)
    intents: list[str] = list(default_intents)

    for rule in pkg_config.get("rules", []):
        match_str = rule.get("match", "")
        if match_str and match_str.lower() in tool_id.lower():
            rule_intents = rule.get("intents", [])
            intents = list(dict.fromkeys(intents + list(rule_intents)))
            break

    if intents == list(default_intents):
        intents = pkg_config.get("default_intents", default_intents)

    mappings = load_tool_id_mappings()
    runtime_to_catalog = mappings.get("runtime_to_catalog", {})

    niwrap_id: str | None = None
    if ".run" in tool_id:
        niwrap_id = tool_id
    else:
        same_package_candidates: list[str] = []
        fallback_candidates: list[str] = []
        package_prefix = f"{package}." if package else ""
        for candidate in runtime_to_catalog.get(tool_id, []):
            candidate_id = str(candidate or "").strip()
            if not candidate_id.endswith(".run") or "." not in candidate_id:
                continue
            if package_prefix and candidate_id.startswith(package_prefix):
                same_package_candidates.append(candidate_id)
            else:
                fallback_candidates.append(candidate_id)

        ordered_candidates = same_package_candidates + fallback_candidates
        if ordered_candidates:
            niwrap_id = ordered_candidates[0]

    if not niwrap_id:
        niwrap_id = f"{tool_id}.run"

    return modalities, intents, niwrap_id


def _normalize_record_intents(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if item)
    return ()


def _fallback_catalog_record(tool_id: str) -> ToolCatalogRecord:
    tool_lower = tool_id.lower()
    category: str | None = None
    intents: tuple[str, ...] = ()

    known_python: dict[str, tuple[str, tuple[str, ...]]] = {
        "glm_first_level": ("statistical_analysis", ("glm_first_level_fmri",)),
        "glm_second_level": ("statistical_analysis", ("glm_second_level_group",)),
        "connectivity_matrix": ("connectivity", ("connectivity_analysis",)),
        "seed_based_fc": ("connectivity", ("seed_based_connectivity",)),
        "viz_stat_maps": ("visualization", ("visualization", "fmri_visualization")),
        "surface_projection": ("visualization", ("visualization", "surface_ops")),
        "pipeline.search": ("workflow", ("pipeline_search",)),
        "freesurfer_recon_all": ("preprocessing", ("cortical_reconstruction",)),
        "extract_timeseries": ("statistical_analysis", ("roi_timeseries_fmri",)),
        "fetch_atlas": ("data_management", ("fetch_atlas_parcellation",)),
    }
    if tool_lower in known_python:
        category, intents = known_python[tool_lower]
    elif tool_lower.startswith("mcp."):
        category = "mcp"
        intents = ("mcp_tool",)
    elif any(kw in tool_lower for kw in ["br_kg", "graph", "concept", "coordinate"]):
        category = "knowledge_graph"
        intents = ("knowledge_graph_query",)
    elif any(kw in tool_lower for kw in ["gemini", "openai", "claude"]):
        category = "statistical_analysis"
        intents = ("llm_query",)
    elif any(kw in tool_lower for kw in ["dataset", "openneuro", "data"]):
        category = "data_management"
        intents = ("data_access",)
    elif tool_lower == "multiple_comparison_correction":
        category = "statistical_inference"
        intents = ("statistical_inference", "multiple_comparison_correction")
    elif "meta_analysis" in tool_lower:
        category = "meta_analysis"
        intents = ("meta_analysis",)
    elif "viz" in tool_lower:
        category = "visualization"
        intents = ("visualization",)
    elif "connectivity" in tool_lower:
        category = "connectivity"
        intents = ("connectivity_analysis",)
    elif "literature" in tool_lower:
        category = "meta_analysis"
        intents = ("literature_search",)
    elif "advanced_analysis" in tool_lower:
        category = "advanced_analysis"
        intents = ("advanced_analysis",)
    elif tool_lower.startswith("fsl."):
        category = "preprocessing"
        if "bet" in tool_lower:
            intents = ("skull_strip_mri",)
        elif "flirt" in tool_lower:
            intents = ("linear_registration",)
        elif "fnirt" in tool_lower:
            intents = ("nonlinear_registration", "registration_to_mni")
        elif "feat" in tool_lower:
            intents = ("fmri_glm_analysis",)
        elif "melodic" in tool_lower:
            intents = ("ica_decomposition",)
        elif "bedpostx" in tool_lower:
            intents = ("diffusion_modeling", "dmri_tractography")
        elif "palm" in tool_lower:
            intents = ("permutation_testing",)
        elif "fix" in tool_lower:
            intents = ("ica_denoising",)
        else:
            intents = ("fsl_processing",)
    elif tool_lower.startswith("afni."):
        category = "preprocessing"
        if "clustsim" in tool_lower:
            intents = ("afni_clustsim_correction",)
        elif "deconvolve" in tool_lower:
            intents = ("fmri_glm_analysis",)
        else:
            intents = ("afni_processing",)
    elif tool_lower.startswith("ants."):
        category = "registration"
        intents = ("ants_registration",)
    elif tool_lower.startswith("freesurfer."):
        category = "preprocessing"
        intents = ("cortical_reconstruction",)

    if category == "mcp":
        description = f"{tool_id} (MCP tool)"
    else:
        category = None
        description = (
            f"{tool_id}: " + ", ".join(intents)
            if intents
            else tool_id.replace(".", " ").replace("_", " ").title()
        )
    return ToolCatalogRecord(
        name=tool_id,
        description=description[:500],
        category=category,
        intents=intents,
    )


def iter_catalog_tool_records(exposed_only: bool = True) -> list[ToolCatalogRecord]:
    """Return BR-KG-local catalog records for structured fallback search."""

    catalog = load_tools_catalog()
    categories_config = load_categories()
    niwrap_map = load_niwrap_mapping()
    alias_map = get_exposed_alias_map()
    tool_ids = (
        list(load_exposed_tools() or []) if exposed_only else sorted(catalog.keys())
    )
    tool_ids = [
        tool_id for tool_id in tool_ids if not str(tool_id).startswith("workflow_")
    ]

    records: list[ToolCatalogRecord] = []
    for tool_id in dict.fromkeys(tool_ids):
        catalog_id = resolve_catalog_tool_id(
            tool_id,
            exposed_only=exposed_only,
            alias_map=alias_map,
        )
        entry = catalog.get(catalog_id)
        if not isinstance(entry, dict):
            records.append(_fallback_catalog_record(tool_id))
            continue

        intents = _normalize_record_intents(entry.get("intents"))
        runtime_kind = entry.get("runtime_kind") or entry.get("backend")
        if not intents and runtime_kind == "container":
            package = entry.get("package") or catalog_id.split(".")[0]
            _, niwrap_intents, _ = resolve_niwrap_metadata(
                catalog_id,
                package,
                niwrap_map,
            )
            intents = tuple(niwrap_intents)
        category = entry.get("category") or resolve_category(tool_id, categories_config)
        description = str(entry.get("description") or "").strip()
        if not description or description.startswith("Tool:"):
            description = (
                f"{tool_id}: " + ", ".join(intents)
                if intents
                else tool_id.replace(".", " ")
            )
        records.append(
            ToolCatalogRecord(
                name=tool_id,
                description=description[:500],
                category=category,
                intents=intents,
            )
        )

    return records


@lru_cache(maxsize=1)
def load_intent_config() -> dict[str, Any]:
    """Load intent priority/filters for primary_intent selection."""
    # New preferred name (kept separate from tool catalog artifacts).
    # Backward compatible fallback: tool_intents.yaml
    candidates = [
        CONFIGS_DIR / "intent_priority.yaml",
        CONFIGS_DIR / "tool_intents.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
            return _normalize_intent_config(data)
    return {}


def _normalize_intent_config(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize intent config for robust lookups (case-insensitive + op key aliases)."""
    if not isinstance(data, dict):
        return {}

    # Normalize intent aliases to be case-insensitive.
    aliases = data.get("aliases")
    if isinstance(aliases, dict):
        data["aliases"] = {
            str(k).lower(): v for k, v in aliases.items() if k is not None
        }

    # Normalize op_key_aliases keys so config can use human-friendly spellings
    # like "film_gls" or "3dDeconvolve" (we always look up by normalized op_key).
    op_key_aliases = data.get("op_key_aliases")
    if isinstance(op_key_aliases, dict):
        normalized: dict[str, Any] = {}
        for raw_key, method in op_key_aliases.items():
            if raw_key is None:
                continue
            key = normalize_op_key(str(raw_key))
            if not key:
                continue
            if key in normalized and normalized[key] != method:
                # Prefer the first mapping to avoid config order affecting behavior.
                continue
            normalized[key] = method
        data["op_key_aliases"] = normalized

    # Normalize op_key_prefix_aliases keys to normalized op_key prefixes.
    op_key_prefix_aliases = data.get("op_key_prefix_aliases")
    if isinstance(op_key_prefix_aliases, dict):
        normalized_prefixes: dict[str, Any] = {}
        for raw_prefix, method in op_key_prefix_aliases.items():
            if raw_prefix is None:
                continue
            prefix = normalize_op_key(str(raw_prefix))
            if not prefix:
                continue
            if prefix in normalized_prefixes and normalized_prefixes[prefix] != method:
                continue
            normalized_prefixes[prefix] = method
        data["op_key_prefix_aliases"] = normalized_prefixes

    # Pre-compile op_key_patterns (regex on normalized op_key) for fast lookups.
    op_key_patterns = data.get("op_key_patterns")
    compiled: list[tuple[re.Pattern[str], str]] = []
    if isinstance(op_key_patterns, list):
        for item in op_key_patterns:
            if not isinstance(item, dict):
                continue
            pattern = item.get("pattern")
            method = item.get("method")
            if not pattern or not method:
                continue
            try:
                compiled.append((re.compile(str(pattern)), str(method)))
            except re.error:
                continue
    if compiled:
        data["op_key_patterns_compiled"] = compiled

    return data


@lru_cache(maxsize=1)
def load_default_versions_config() -> dict[str, Any]:
    """Load pinned default versions for (software, op_key) groups."""
    path = CONFIGS_DIR / "tool_default_versions.yaml"
    if not path.exists():
        return {}
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_exposure_policy() -> dict[str, Any]:
    """Load exposure policy used to derive Tool.exposed flags."""
    path = CONFIGS_DIR / "tool_exposure_policy.yaml"
    if not path.exists():
        return {}
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def parse_tool_id(tool_id: str, package: str | None = None) -> dict[str, str | None]:
    """Parse tool_id into software/version/op/entrypoint."""
    entrypoint = None
    base = tool_id
    if base.endswith(".run"):
        entrypoint = "run"
        base = base[:-4]

    parts = base.split(".") if base else []
    software = package or (parts[0] if parts else None)
    start_idx = 1 if parts and software == parts[0] else 0

    version_parts: list[str] = []
    i = start_idx
    while i < len(parts) and parts[i].isdigit():
        version_parts.append(parts[i])
        i += 1
    version = ".".join(version_parts) if version_parts else None

    op_parts = parts[i:] if i < len(parts) else []
    op = ".".join(op_parts) if op_parts else (parts[-1] if parts else None)

    return {
        "software": software,
        "version": version,
        "op": op,
        "entrypoint": entrypoint,
    }


def normalize_op_key(op: str | None) -> str | None:
    if not op:
        return None
    return re.sub(r"[^a-z0-9]+", "", op.lower())


def resolve_op_key_method(
    op_key: str | None, intent_config: dict[str, Any]
) -> str | None:
    """Resolve a canonical method intent from a normalized op_key.

    Precedence: exact alias → prefix alias → regex patterns.
    """
    if not op_key or not intent_config:
        return None

    op_key_aliases = intent_config.get("op_key_aliases", {}) or {}
    if isinstance(op_key_aliases, dict):
        method = op_key_aliases.get(op_key)
        if method:
            return str(method)

    op_key_prefix_aliases = intent_config.get("op_key_prefix_aliases", {}) or {}
    if isinstance(op_key_prefix_aliases, dict) and op_key_prefix_aliases:
        # Prefer the longest prefix match (more specific).
        for prefix, method in sorted(
            op_key_prefix_aliases.items(), key=lambda kv: -len(kv[0])
        ):
            if prefix and op_key.startswith(prefix):
                return str(method)

    compiled = intent_config.get("op_key_patterns_compiled") or []
    if compiled:
        for regex, method in compiled:
            if regex.search(op_key):
                return str(method)

    # Fallback: compile raw patterns if provided but not normalized (e.g., tests).
    raw_patterns = intent_config.get("op_key_patterns")
    if isinstance(raw_patterns, list):
        for item in raw_patterns:
            if not isinstance(item, dict):
                continue
            pattern = item.get("pattern")
            method = item.get("method")
            if not pattern or not method:
                continue
            try:
                if re.search(str(pattern), op_key):
                    return str(method)
            except re.error:
                continue

    return None


def _version_tuple(version: str | None) -> tuple[int, ...] | None:
    if not version:
        return None
    parts = version.split(".")
    if all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return None


def _pick_default_tool_id(
    tool_ids: list[str],
    meta_map: dict[str, dict[str, Any]],
    pinned_tool_ids: set[str],
    pinned_version: str | None,
) -> str | None:
    for tid in tool_ids:
        if tid in pinned_tool_ids:
            return tid
    if pinned_version:
        for tid in tool_ids:
            if meta_map.get(tid, {}).get("version") == pinned_version:
                return tid
    ranked: list[tuple[int, tuple[int, ...] | tuple[()], str]] = []
    for tid in tool_ids:
        vtuple = _version_tuple(meta_map.get(tid, {}).get("version"))
        if vtuple is not None:
            ranked.append((1, vtuple, tid))
        else:
            ranked.append((0, (), tid))
    if not ranked:
        return None
    ranked.sort()
    return ranked[-1][2]


def build_tool_meta(
    caps: dict[str, Any],
    catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build parsed metadata for each tool (software/version/op/op_key/group)."""
    meta_map: dict[str, dict[str, Any]] = {}
    for tool in caps.get("tools", []) or []:
        tool_id = tool.get("id")
        if not tool_id:
            continue
        catalog_entry = catalog.get(tool_id) if catalog else None
        package = tool.get("package") or (catalog_entry or {}).get("package")
        parsed = parse_tool_id(tool_id, package)
        software = parsed.get("software") or package or tool_id.split(".")[0]
        version = parsed.get("version") or tool.get("version")
        op = parsed.get("op") or tool_id
        op_key = normalize_op_key(op) or normalize_op_key(tool_id)
        group_id = f"{software}:{op_key}" if software and op_key else None
        meta_map[tool_id] = {
            "software": software,
            "version": version,
            "op": op,
            "op_key": op_key,
            "group_id": group_id,
        }
    return meta_map


def select_default_tools(
    meta_map: dict[str, dict[str, Any]],
    default_config: dict[str, Any],
) -> dict[str, str]:
    """Choose default tool_id per (software, op_key) group."""
    pinned_tool_ids = set(default_config.get("default_tool_ids", []) or [])
    pinned_versions = default_config.get("default_versions", {}) or {}

    groups: dict[str, list[str]] = {}
    for tid, meta in meta_map.items():
        group_id = meta.get("group_id")
        if not group_id:
            continue
        groups.setdefault(group_id, []).append(tid)

    default_by_group: dict[str, str] = {}
    for group_id, tool_ids in groups.items():
        software, _, op_key = group_id.partition(":")
        pinned_version = None
        if software and op_key:
            pinned_version = (pinned_versions.get(software) or {}).get(op_key)
        default_tid = _pick_default_tool_id(
            tool_ids, meta_map, pinned_tool_ids, pinned_version
        )
        if default_tid:
            default_by_group[group_id] = default_tid
    return default_by_group


def _policy_allows(value: str | None, allow: set[str], deny: set[str]) -> bool:
    if value in deny:
        return False
    if allow and value not in allow:
        return False
    return True


def select_primary_intent(
    intents: list[str],
    category: str | None,
    families: list[str],
    intent_config: dict[str, Any],
) -> str | None:
    """Pick a primary intent, excluding implementation-only intents."""
    default_impl_intents = {
        "generic_container_op",
        "python_op",
        "mcp_tool",
        "wrapper_tool",
        "service_tool",
    }
    impl_intents = set(intent_config.get("impl_intents", []) or default_impl_intents)
    priority = (
        intent_config.get("priority", [])
        or intent_config.get("method_priority", [])
        or []
    )

    # Canonicalize intents/category/families via config aliases (stable cross-software method ids).
    aliases = intent_config.get("aliases", {}) or {}

    def _alias(value: str | None) -> str | None:
        if not value:
            return value
        key = str(value)
        return aliases.get(key, aliases.get(key.lower(), key))

    canonicalized: list[str] = []
    for intent in intents:
        if not intent:
            continue
        mapped = _alias(intent)
        if mapped and mapped not in canonicalized:
            canonicalized.append(mapped)

    filtered = [i for i in canonicalized if i and i not in impl_intents]
    if priority:
        for intent in priority:
            if intent in filtered:
                return intent
    if filtered:
        return filtered[0]
    if category:
        return _alias(category)
    if families:
        return _alias(families[0])
    return None


def load_capabilities(path: Path | str) -> dict[str, Any]:
    """Load a capabilities YAML/JSON file into a dict."""

    with Path(path).open("r") as f:
        data = yaml.safe_load(f) or {}
    return data


def _build_version_id(tool: dict[str, Any]) -> str:
    """Derive a deterministic version identifier for the tool.

    Preference order:
    1) explicit version field (semver or string)
    2) container digest or image tag
    3) python module reference
    4) fallback to tool id with suffix
    """

    if version := tool.get("version"):
        return f"{tool['id']}@{version}"

    container = tool.get("container") or {}
    if digest := container.get("digest"):
        return f"{tool['id']}@image:{digest}"
    if image := container.get("image"):
        return f"{tool['id']}@image:{image}"

    py = tool.get("python") or {}
    if module := py.get("module"):
        fn = py.get("function") or ""
        return f"{tool['id']}@py:{module}:{fn}"

    return f"{tool['id']}@unknown"


def iter_tools(
    caps: dict[str, Any],
    catalog: dict[str, dict[str, Any]] | None = None,
    exposed_tools: set[str] | None = None,
    categories_config: dict[str, Any] | None = None,
    niwrap_map: dict[str, Any] | None = None,
    intent_config: dict[str, Any] | None = None,
    tool_meta: dict[str, dict[str, Any]] | None = None,
    default_by_group: dict[str, str] | None = None,
    exposure_policy: dict[str, Any] | None = None,
) -> Iterable[
    tuple[
        dict[str, Any], dict[str, Any], list[tuple[str, str, str]], list[str], list[str]
    ]
]:
    """Yield tuples describing tools and their graph edges.

    Returns: (tool_node, version_node, resource_edges, modalities, families)
    resource_edges use the form (tool_id, resource_key, RELATION)
    """

    # Pre-compute exposure policy sets once per ingestion run.
    allow_primary: set[str] = set()
    deny_primary: set[str] = set()
    allow_soft: set[str] = set()
    deny_soft: set[str] = set()
    allow_runtime: set[str] = set()
    deny_runtime: set[str] = set()
    allow_ops: set[str] = set()
    deny_ops: set[str] = set()
    deny_op_key_prefixes_by_software: dict[str, list[str]] = {}
    deny_op_prefixes_by_software: dict[str, list[str]] = {}

    if exposure_policy is not None:
        allow_primary = set(exposure_policy.get("allow_primary_intents", []) or [])
        if (
            not allow_primary
            and exposure_policy.get("derive_allow_primary_from_intent_priority")
            and intent_config
        ):
            priority = (
                intent_config.get("priority")
                or intent_config.get("method_priority")
                or []
            )
            allow_primary = set(priority or [])

        deny_primary = set(exposure_policy.get("deny_primary_intents", []) or [])

        allow_soft = {
            str(s).lower()
            for s in (exposure_policy.get("allow_softwares", []) or [])
            if s is not None
        }
        deny_soft = {
            str(s).lower()
            for s in (exposure_policy.get("deny_softwares", []) or [])
            if s is not None
        }

        allow_runtime = {
            str(s).lower()
            for s in (exposure_policy.get("allow_runtime_kinds", []) or [])
            if s is not None
        }
        deny_runtime = {
            str(s).lower()
            for s in (exposure_policy.get("deny_runtime_kinds", []) or [])
            if s is not None
        }

        allow_ops = {
            k
            for k in (
                normalize_op_key(v)
                for v in (exposure_policy.get("allow_op_keys", []) or [])
            )
            if k
        }
        deny_ops = {
            k
            for k in (
                normalize_op_key(v)
                for v in (exposure_policy.get("deny_op_keys", []) or [])
            )
            if k
        }

        raw_prefixes = exposure_policy.get("deny_op_key_prefixes_by_software", {}) or {}
        if isinstance(raw_prefixes, dict):
            for sw, prefixes in raw_prefixes.items():
                if not sw or not isinstance(prefixes, list):
                    continue
                normed = [p for p in (normalize_op_key(x) for x in prefixes) if p]
                if normed:
                    deny_op_key_prefixes_by_software[str(sw).lower()] = normed

        raw_op_prefixes = exposure_policy.get("deny_op_prefixes_by_software", {}) or {}
        if isinstance(raw_op_prefixes, dict):
            for sw, prefixes in raw_op_prefixes.items():
                if not sw or not isinstance(prefixes, list):
                    continue
                cleaned = [str(p) for p in prefixes if p is not None]
                if cleaned:
                    deny_op_prefixes_by_software[str(sw).lower()] = cleaned

    for tool in caps.get("tools", []) or []:
        tool_id = tool.get("id")
        if not tool_id:
            continue

        runtime_kind = tool.get("runtime_kind") or tool.get("backend") or "container"
        catalog_entry: dict[str, Any] | None = None
        if catalog is not None:
            catalog_entry = catalog.get(tool_id)

        intents: list[str] = []
        intents_from_niwrap = False
        category: str | None = None
        kind: str | None = None
        display_name: str | None = None
        source: str | None = None
        confidence: float | None = None
        runtime: str | None = None
        mcp_tool: bool | None = None

        if catalog_entry:
            raw_intents = catalog_entry.get("intents") or []
            if isinstance(raw_intents, str):
                intents = [raw_intents]
            else:
                intents = list(raw_intents)
            category = catalog_entry.get("category")
            display_name = catalog_entry.get("display_name")
            source = catalog_entry.get("source")
            confidence = catalog_entry.get("confidence")
            runtime = catalog_entry.get("runtime")
            mcp_tool = catalog_entry.get("mcp_tool")

        # Enrich missing intents/category for NiWrap tools
        if (not intents) and runtime_kind == "container" and niwrap_map:
            package = (
                tool.get("package")
                or (catalog_entry or {}).get("package")
                or tool_id.split(".")[0]
            )
            _, niwrap_intents, _ = resolve_niwrap_metadata(tool_id, package, niwrap_map)
            intents = list(niwrap_intents)
            intents_from_niwrap = True

        if not category and categories_config:
            category = resolve_category(tool_id, categories_config)

        if category:
            kind = CATEGORY_TO_KIND.get(category)

        modalities = tool.get("modality") or tool.get("modalities") or []
        families = tool.get("capabilities") or []

        description = tool.get("description")
        if not description and catalog_entry:
            description = catalog_entry.get("description")

        meta = (tool_meta or {}).get(tool_id, {})
        software = meta.get("software")
        version = meta.get("version")
        op = meta.get("op")
        op_key = meta.get("op_key")
        group_id = meta.get("group_id")
        is_default = bool(
            group_id and default_by_group and default_by_group.get(group_id) == tool_id
        )

        # Apply intent aliases and op_key-to-method mapping before selecting primary_intent.
        if intent_config is None:
            intent_config = {}
        default_impl_intents = {
            "generic_container_op",
            "python_op",
            "mcp_tool",
            "wrapper_tool",
            "service_tool",
        }
        impl_intents = set(
            intent_config.get("impl_intents", []) or default_impl_intents
        )
        aliases = intent_config.get("aliases", {}) or {}

        canonical_intents: list[str] = []
        for intent in intents:
            if not intent:
                continue
            mapped = aliases.get(intent, aliases.get(str(intent).lower(), intent))
            if mapped and mapped not in canonical_intents:
                canonical_intents.append(mapped)

        # Only inject an op_key-based method intent when there are no method intents yet.
        mapped_method = resolve_op_key_method(op_key, intent_config) if op_key else None
        method_intents = [i for i in canonical_intents if i and i not in impl_intents]
        if mapped_method:
            if not method_intents:
                # No method intents yet: inject from op_key mapping.
                if mapped_method not in canonical_intents:
                    canonical_intents.append(mapped_method)
            elif (
                intents_from_niwrap
                and len(method_intents) == 1
                and method_intents[0] != mapped_method
            ):
                # NiWrap-derived intents are a good default, but for some ops the op_key is more reliable
                # (e.g. FEATquery is extraction, not "fit a GLM"). Allow op_key_aliases to override
                # a single inferred method intent, while keeping implementation intents.
                canonical_intents = [i for i in canonical_intents if i in impl_intents]
                canonical_intents.append(mapped_method)

        intents = canonical_intents
        primary_intent = select_primary_intent(
            intents, category, list(families), intent_config
        )

        tool_node = {
            "tool_id": tool_id,
            "name": tool.get("name", tool_id),
            "domain": tool.get("domain") or tool.get("package"),
            "runtime_kind": runtime_kind,
            "description": description,
            "homepage_url": tool.get("homepage_url"),
            "repo_url": tool.get("repo_url"),
            "status": tool.get("status"),
        }
        if software:
            tool_node["software"] = software
        if version:
            tool_node["version"] = version
        if op:
            tool_node["op"] = op
        if op_key:
            tool_node["op_key"] = op_key
        if group_id:
            tool_node["default_group_id"] = group_id
            tool_node["exposure_group"] = group_id
        tool_node["is_default"] = is_default
        if display_name:
            tool_node["display_name"] = display_name
        if intents:
            tool_node["intents"] = intents
        if category:
            tool_node["category"] = category
        if kind:
            tool_node["kind"] = kind
        if primary_intent:
            tool_node["primary_intent"] = primary_intent
        if exposure_policy is not None:
            exposed = is_default
            exposed = exposed and _policy_allows(
                primary_intent, allow_primary, deny_primary
            )
            exposed = exposed and _policy_allows(
                software.lower() if software else software, allow_soft, deny_soft
            )
            exposed = exposed and _policy_allows(
                runtime_kind.lower(), allow_runtime, deny_runtime
            )
            exposed = exposed and _policy_allows(op_key, allow_ops, deny_ops)

            # Extra safety gates for known long-tail namespaces.
            if exposed:
                sw = software.lower() if software else ""
                if sw and op_key:
                    prefixes = deny_op_key_prefixes_by_software.get(sw) or []
                    if any(op_key.startswith(p) for p in prefixes):
                        exposed = False
                if exposed and sw and op:
                    prefixes = deny_op_prefixes_by_software.get(sw) or []
                    if any(str(op).startswith(p) for p in prefixes):
                        exposed = False
            tool_node["exposed"] = bool(exposed)
        elif exposed_tools is not None:
            tool_node["exposed"] = tool_id in exposed_tools
        if source:
            tool_node["source"] = source
        if confidence is not None:
            tool_node["confidence"] = confidence
        if runtime:
            tool_node["runtime"] = runtime
        if mcp_tool is not None:
            tool_node["mcp_tool"] = bool(mcp_tool)

        version_node: dict[str, Any] = {
            "version_id": _build_version_id(tool),
            "tool_id": tool_id,
            "semver": tool.get("version"),
            "container_image": tool.get("container", {}).get("image"),
            "container_digest": tool.get("container", {}).get("digest"),
        }
        if software:
            version_node["software"] = software
        if version:
            version_node["version"] = version
        if op:
            version_node["op"] = op

        py_spec = tool.get("python") or {}
        if py_spec:
            version_node["python_module"] = py_spec.get("module")
            version_node["python_function"] = py_spec.get("function")

        resource_edges: list[tuple[str, str, str]] = []
        for res in tool.get("consumes", []) or []:
            ResourceType.validate(res)
            resource_edges.append((tool_id, res, "CONSUMES_RESOURCE"))
        for res in tool.get("produces", []) or []:
            ResourceType.validate(res)
            resource_edges.append((tool_id, res, "PRODUCES_RESOURCE"))

        yield tool_node, version_node, resource_edges, list(modalities), list(families)


def _merge_evidence(tx: Any, tool_id: str, evidence: dict[str, Any]) -> None:
    def _merge_data_resource(resource_id: str) -> None:
        tx.merge_node(
            "DataResource",
            "id",
            {"id": resource_id, "resource_id": resource_id},
        )

    pubs = evidence.get("publications") or []
    for pub in pubs:
        doi = pub.get("doi") if isinstance(pub, dict) else pub
        if not doi:
            continue
        tx.merge_node("Publication", "doi", {"doi": doi})
        tx.merge_rel(
            "Tool", "tool_id", tool_id, "DOCUMENTED_IN", "Publication", "doi", doi
        )

    validated = evidence.get("validated_on_collections") or []
    for ds in validated:
        ds_id = ds.get("id") if isinstance(ds, dict) else ds
        if not ds_id:
            continue
        _merge_data_resource(ds_id)
        tx.merge_rel(
            "Tool",
            "tool_id",
            tool_id,
            "VALIDATED_ON",
            "DataResource",
            "id",
            ds_id,
        )


def ingest(
    tx: Any, caps_path: Path | str, evidence: dict[str, Any] | None = None
) -> None:
    """Ingest a capabilities file into the NeoKG transaction ``tx``.

    ``tx`` only needs ``merge_node`` and ``merge_rel`` methods; tests provide a
    stub with this minimal API.

    Version ID fallback order: semver > container digest > container image >
    python module:function > unknown.
    """

    caps = load_capabilities(caps_path)
    catalog = load_tools_catalog()
    exposed_tools = set(load_exposed_tools() or [])
    categories_config = load_categories()
    niwrap_map = load_niwrap_mapping()
    intent_config = load_intent_config()
    default_versions_config = load_default_versions_config()
    exposure_policy = load_exposure_policy()
    if not exposure_policy:
        exposure_policy = None
    tool_meta = build_tool_meta(caps, catalog)
    default_by_group = select_default_tools(tool_meta, default_versions_config)
    evidence = evidence or {}
    # Allow evidence files shaped like {tools: {id: {...}}}
    if "tools" in evidence and isinstance(evidence["tools"], dict):
        evidence = evidence["tools"]

    for tool_node, version_node, resource_edges, modalities, families in iter_tools(
        caps,
        catalog=catalog,
        exposed_tools=exposed_tools,
        categories_config=categories_config,
        niwrap_map=niwrap_map,
        intent_config=intent_config,
        tool_meta=tool_meta,
        default_by_group=default_by_group,
        exposure_policy=exposure_policy,
    ):
        tool_id = tool_node["tool_id"]
        version_id = version_node["version_id"]

        tx.merge_node("Tool", "tool_id", tool_node)
        tx.merge_node("ToolVersion", "version_id", version_node)
        tx.merge_rel(
            "Tool",
            "tool_id",
            tool_id,
            "HAS_VERSION",
            "ToolVersion",
            "version_id",
            version_id,
        )

        for _, res, rel in resource_edges:
            # Use ResourceType nodes to stay consistent with KG resource ontology
            tx.merge_node("ResourceType", "name", {"name": res})
            tx.merge_rel(
                "ToolVersion",
                "version_id",
                version_id,
                rel,
                "ResourceType",
                "name",
                res,
            )

        for mod in modalities:
            tx.merge_node("Modality", "name", {"name": mod})
            tx.merge_rel(
                "Tool", "tool_id", tool_id, "SUPPORTS_MODALITY", "Modality", "name", mod
            )

        for fam in families:
            tx.merge_node("TaskFamily", "name", {"name": fam})
            tx.merge_rel(
                "Tool",
                "tool_id",
                tool_id,
                "IMPLEMENTS_FAMILY",
                "TaskFamily",
                "name",
                fam,
            )

        if ev := evidence.get(tool_id):
            _merge_evidence(tx, tool_id, ev)


def ingest_tool_run(tx: Any, provenance: dict[str, Any]) -> None:
    """Ingest a single tool run provenance record.

    Expected provenance keys: job_id/run_id, tool_id, version_id, runtime_kind,
    status, started_at, finished_at, parameters (dict), inputs (list of ids),
    outputs (list of ids).
    """

    run_id = provenance.get("run_id") or provenance.get("job_id")
    tool_id = provenance.get("tool_id")
    version_id = provenance.get("version_id")
    if not (run_id and tool_id and version_id):
        raise ValueError(
            "run_id, tool_id, and version_id are required for tool run ingestion"
        )

    tx.merge_node("Tool", "tool_id", {"tool_id": tool_id})
    tx.merge_node("ToolVersion", "version_id", {"version_id": version_id})
    tx.merge_rel(
        "Tool",
        "tool_id",
        tool_id,
        "HAS_VERSION",
        "ToolVersion",
        "version_id",
        version_id,
    )

    tx.merge_node(
        "ToolRun",
        "run_id",
        {
            "run_id": run_id,
            "job_id": provenance.get("job_id"),
            "status": provenance.get("status"),
            "started_at": provenance.get("started_at"),
            "finished_at": provenance.get("finished_at"),
            "parameters_json": provenance.get("parameters_json")
            or (
                yaml.safe_dump(provenance.get("parameters"))
                if provenance.get("parameters")
                else None
            ),
            "runtime_kind": provenance.get("runtime_kind"),
        },
    )
    tx.merge_rel(
        "ToolRun",
        "run_id",
        run_id,
        "EXECUTED_VERSION",
        "ToolVersion",
        "version_id",
        version_id,
    )

    for ds in provenance.get("inputs", []) or []:
        ds_id = ds.get("id") if isinstance(ds, dict) else ds
        if not ds_id:
            continue
        tx.merge_node("DataResource", "id", {"id": ds_id, "resource_id": ds_id})
        tx.merge_rel(
            "ToolRun", "run_id", run_id, "USED_RESOURCE", "DataResource", "id", ds_id
        )

    for ds in provenance.get("outputs", []) or []:
        ds_id = ds.get("id") if isinstance(ds, dict) else ds
        if not ds_id:
            continue
        tx.merge_node("DataResource", "id", {"id": ds_id, "resource_id": ds_id})
        tx.merge_rel(
            "ToolRun",
            "run_id",
            run_id,
            "GENERATED_RESOURCE",
            "DataResource",
            "id",
            ds_id,
        )
