"""
Catalog Loader for Unified ToolSpec System

This module merges configuration from multiple sources to build a unified
list of ToolSpec objects for exposed tools.

Config sources:
- configs/grandmaster/toolset_vfinal.yaml - primary whitelist source
- configs/catalog/exposed_tools.yaml - legacy/fallback whitelist source
- configs/tools_catalog_merged.json - tool catalog with metadata
- configs/tool_categories.yaml - category definitions and patterns
- configs/catalog/niwrap_mapping.yaml - NiWrap metadata (modalities/intents)
"""

import json
import logging
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import get_config_root
from brain_researcher.services.tools.spec import (
    Backend,
    Kind,
    ToolSpec,
    infer_requires_runtime,
    normalize_hard_dependencies,
    normalize_implementation_level,
    normalize_qc_spec,
)

logger = logging.getLogger(__name__)

# Path to configs directory
CONFIGS_DIR = get_config_root()
_WORKFLOW_BRIDGE_MODULE = "brain_researcher.services.tools.catalog_loader"

_EXPOSED_ALIAS_MAP: Dict[str, str] = {
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


def _filter_agent_visible_tool_ids(tool_ids: List[str]) -> List[str]:
    """Apply local-first filtering to agent-facing exposed tool surfaces."""

    try:
        from brain_researcher.services.agent.tool_allowlist_loader import (
            filter_local_first_tool_ids,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to import local-first filter: %s", exc)
        return list(tool_ids)

    return filter_local_first_tool_ids(list(tool_ids))


# Category to Kind mapping
CATEGORY_TO_KIND: Dict[str, Kind] = {
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


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for item in items:
        candidate = str(item or "").strip()
        if not candidate or candidate in seen:
            continue
        deduped.append(candidate)
        seen.add(candidate)
    return deduped


def _camel_to_snake(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_").lower()


def _heuristic_runtime_candidates(tool_id: str) -> List[str]:
    """Best-effort runtime-name fallbacks for planner/catalog-style IDs."""

    resolved = str(tool_id or "").strip()
    if not resolved:
        return []

    candidates: List[str] = []

    if resolved.startswith("python.") and resolved.endswith(".run"):
        inner = resolved[len("python.") : -len(".run")]
        if inner:
            candidates.append(inner)
            if inner.endswith("_tool"):
                candidates.append(inner[: -len("_tool")])
            if inner.endswith("_tools"):
                candidates.append(inner[: -len("_tools")])

    if resolved.endswith(".run") and not resolved.startswith("python."):
        inner = resolved[: -len(".run")]
        if inner and "." in inner:
            package = inner.split(".", 1)[0]
            tail = inner.rsplit(".", 1)[-1]
            tail_snake = _camel_to_snake(tail)
            if package and tail_snake:
                if tail_snake.startswith(f"{package}_"):
                    candidates.append(tail_snake)
                candidates.append(f"{package}_{tail_snake}")

    return _dedupe_preserve_order(candidates)


def _heuristic_catalog_candidates(tool_id: str) -> List[str]:
    """Best-effort planner/catalog-name fallbacks for runtime/exposed IDs.

    Keep this function side-effect free. Calling back into the planner catalog
    loader from here creates a recursion loop because planner canonicalization
    itself consults ``resolve_runtime_tool_ids``.
    """

    resolved = str(tool_id or "").strip()
    if not resolved or "." in resolved:
        return []

    candidates: List[str] = [f"python.{resolved}.run"]

    if "_" in resolved:
        package, remainder = resolved.split("_", 1)
        if package and remainder:
            candidates.append(f"{package}.{remainder}.run")

    return _dedupe_preserve_order(candidates)


def get_exposed_alias_map() -> Dict[str, str]:
    """Return a copy of exposed-tool alias mapping."""

    return dict(_EXPOSED_ALIAS_MAP)


def _normalize_mapping_targets(raw: Any) -> Dict[str, List[str]]:
    """Normalize mapping values to list[str] while preserving order."""

    normalized: Dict[str, List[str]] = {}
    if not isinstance(raw, dict):
        return normalized

    for key, value in raw.items():
        key_str = str(key or "").strip()
        if not key_str:
            continue
        targets: List[str] = []
        if isinstance(value, list):
            raw_targets = value
        elif value is None:
            raw_targets = []
        else:
            raw_targets = [value]

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
def load_tool_id_mappings() -> Dict[str, Dict[str, List[str]]]:
    """Load forward catalog->runtime mappings and derive reverse compat aliases."""

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

    # Build reverse map when only forward mappings are declared.
    if not runtime_to_catalog and catalog_to_runtime:
        for catalog_id, runtime_ids in catalog_to_runtime.items():
            for runtime_id in runtime_ids:
                runtime_to_catalog.setdefault(runtime_id, []).append(catalog_id)

    return {
        "catalog_to_runtime": catalog_to_runtime,
        "runtime_to_catalog": runtime_to_catalog,
    }


def _first_targets(raw: Any) -> str | None:
    if isinstance(raw, list):
        for item in raw:
            candidate = str(item or "").strip()
            if candidate:
                return candidate
        return None
    candidate = str(raw or "").strip()
    return candidate or None


def _resolve_primary_runtime_candidate(
    tool_id: str,
    *,
    catalog_to_runtime: Dict[str, List[str]],
    catalog: Dict[str, Any],
    alias_map: Dict[str, str],
) -> str | None:
    resolved = str(tool_id or "").strip()
    if not resolved:
        return None

    explicit = _first_targets(catalog_to_runtime.get(resolved))
    if explicit:
        return explicit

    alias_catalog_id = alias_map.get(resolved)
    if alias_catalog_id:
        explicit = _first_targets(catalog_to_runtime.get(alias_catalog_id))
        if explicit:
            return explicit
        if alias_catalog_id in catalog:
            return alias_catalog_id

    if resolved in catalog:
        return resolved

    if resolved.startswith("python."):
        legacy_name = resolved.rsplit(".", 1)[-1]
        if legacy_name in catalog:
            return legacy_name

    for candidate in _heuristic_runtime_candidates(resolved):
        if candidate in catalog or not candidate.startswith("python."):
            return candidate

    return resolved


def resolve_runtime_tool_ids(tool_id: str, include_self: bool = True) -> List[str]:
    """Resolve runtime-facing candidates for a possibly-legacy tool id.

    Results are ordered by runtime preference and keep legacy planner/catalog
    identifiers out of the returned list.
    """

    resolved = str(tool_id or "").strip()
    if not resolved:
        return []

    alias_map = get_exposed_alias_map()
    mappings = load_tool_id_mappings()
    catalog_to_runtime = mappings.get("catalog_to_runtime", {})
    runtime_to_catalog = mappings.get("runtime_to_catalog", {})
    catalog = load_tools_catalog()

    candidates: List[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        candidate_id = str(candidate or "").strip()
        if not candidate_id or candidate_id in seen:
            return
        candidates.append(candidate_id)
        seen.add(candidate_id)

    primary = _resolve_primary_runtime_candidate(
        resolved,
        catalog_to_runtime=catalog_to_runtime,
        catalog=catalog,
        alias_map=alias_map,
    )
    if include_self and primary:
        _add(primary)

    catalog_seed_ids: List[str] = [resolved]
    alias_catalog_id = alias_map.get(resolved)
    if alias_catalog_id:
        catalog_seed_ids.append(alias_catalog_id)
    if primary:
        catalog_seed_ids.extend(runtime_to_catalog.get(primary, []))

    for heuristic_id in _heuristic_runtime_candidates(resolved):
        _add(heuristic_id)

    for heuristic_id in _heuristic_catalog_candidates(resolved):
        if heuristic_id not in catalog_seed_ids:
            catalog_seed_ids.append(heuristic_id)
    if primary:
        for heuristic_id in _heuristic_catalog_candidates(primary):
            if heuristic_id not in catalog_seed_ids:
                catalog_seed_ids.append(heuristic_id)

    for seed in catalog_seed_ids:
        for runtime_id in catalog_to_runtime.get(seed, []):
            _add(runtime_id)

    if not candidates and include_self and resolved in catalog:
        _add(resolved)

    return candidates


def resolve_catalog_tool_ids(tool_id: str, include_self: bool = True) -> List[str]:
    """Resolve legacy catalog/planner aliases for a runtime tool id.

    This is a compatibility helper only. Internal planner/execution flows should
    prefer runtime canonical IDs directly.
    """

    resolved = str(tool_id or "").strip()
    if not resolved:
        return []

    alias_map = get_exposed_alias_map()
    mappings = load_tool_id_mappings()
    runtime_to_catalog = mappings.get("runtime_to_catalog", {})

    candidates: List[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        candidate_id = str(candidate or "").strip()
        if not candidate_id or candidate_id in seen:
            return
        candidates.append(candidate_id)
        seen.add(candidate_id)

    if include_self:
        _add(resolved)

    seed_ids: List[str] = [resolved]
    alias_catalog_id = alias_map.get(resolved)
    if alias_catalog_id:
        _add(alias_catalog_id)
        seed_ids.append(alias_catalog_id)

    for heuristic_id in _heuristic_catalog_candidates(resolved):
        _add(heuristic_id)
        if heuristic_id not in seed_ids:
            seed_ids.append(heuristic_id)

    for seed in seed_ids:
        for catalog_id in runtime_to_catalog.get(seed, []):
            _add(catalog_id)

    return candidates


@lru_cache(maxsize=8192)
def resolve_primary_runtime_tool_id(tool_id: str) -> str | None:
    """Resolve a single canonical runtime-facing tool id.

    Preference order:
    1. Explicit ``catalog_to_runtime`` mappings.
    2. Existing runtime/tool catalog names.
    3. Legacy ``python.<domain>.<name>`` planner IDs reduced to ``<name>``.
    4. Best-effort runtime candidates from ``resolve_runtime_tool_ids`` that
       already exist in the tool catalog or runtime map.
    """

    resolved = str(tool_id or "").strip()
    if not resolved:
        return None

    mappings = load_tool_id_mappings()
    catalog_to_runtime = mappings.get("catalog_to_runtime", {})
    catalog = load_tools_catalog()
    alias_map = get_exposed_alias_map()

    return _resolve_primary_runtime_candidate(
        resolved,
        catalog_to_runtime=catalog_to_runtime,
        catalog=catalog,
        alias_map=alias_map,
    )


def resolve_catalog_tool_id(
    tool_id: str,
    *,
    exposed_only: bool,
    alias_map: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve external tool id to catalog id when loading exposed tools."""

    if not exposed_only:
        return tool_id
    aliases = alias_map if isinstance(alias_map, dict) else _EXPOSED_ALIAS_MAP
    return aliases.get(tool_id, tool_id)


@lru_cache(maxsize=2)
def load_exposed_tools(*, agent_visible_only: bool = True) -> List[str]:
    """Load whitelist of tools to expose.

    Primary source:
    - configs/grandmaster/toolset_vfinal.yaml -> exposure.exposed

    Fallback source (legacy):
    - configs/catalog/exposed_tools.yaml -> exposed

    Args:
        agent_visible_only: When True, apply local-first hiding for agent-facing
            execution surfaces. When False, keep the full exposed discovery
            surface so search can still discover runtime-gated tools.
    """

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
        logger.warning(f"Exposed tools whitelist not found at {legacy_path}")
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
def load_orchestration_workflows() -> List[str]:
    """Load workflow IDs used by orchestration-first routing."""

    gm_path = CONFIGS_DIR / "grandmaster" / "toolset_vfinal.yaml"
    if gm_path.exists():
        try:
            data = yaml.safe_load(gm_path.read_text()) or {}
            orchestration = (
                data.get("orchestration") if isinstance(data, dict) else None
            )
            if isinstance(orchestration, dict):
                workflows = _normalize_id_list(orchestration.get("workflows"))
                if workflows:
                    return workflows
        except Exception as exc:
            logger.warning("Failed to load orchestration workflows: %s", exc)

    return []


@lru_cache(maxsize=1)
def load_workflow_catalog_ids() -> set[str]:
    """Load declared workflow IDs from configs/workflows/workflow_catalog.yaml."""

    workflow_path = CONFIGS_DIR / "workflows" / "workflow_catalog.yaml"
    if not workflow_path.exists():
        return set()
    try:
        data = yaml.safe_load(workflow_path.read_text()) or {}
        workflow_defs = data.get("workflows") if isinstance(data, dict) else None
        if not isinstance(workflow_defs, list):
            return set()
        workflow_ids = set()
        for item in workflow_defs:
            if not isinstance(item, dict):
                continue
            workflow_id = str(item.get("id") or "").strip()
            if workflow_id:
                workflow_ids.add(workflow_id)
        return workflow_ids
    except Exception as exc:
        logger.warning("Failed to load workflow catalog IDs: %s", exc)
        return set()


def is_workflow_tool_id(tool_id: str) -> bool:
    """Return True when tool_id points to a declarative workflow entry."""

    tid = str(tool_id or "").strip()
    if not tid:
        return False
    if tid.startswith("workflow_"):
        return True
    return tid in load_workflow_catalog_ids() or tid in set(
        load_orchestration_workflows()
    )


@lru_cache(maxsize=1)
def _workflow_bridge_ids() -> tuple[str, ...]:
    """Workflow IDs that should resolve through runtime workflow wrappers."""

    workflow_ids = set(load_workflow_catalog_ids()) | set(
        load_orchestration_workflows()
    )
    return tuple(sorted(wid for wid in workflow_ids if wid))


@lru_cache(maxsize=1)
def _workflow_bridge_tools() -> tuple[Any, ...]:
    """Materialize bridge wrappers so workflow ToolSpecs resolve executable classes."""

    try:
        from brain_researcher.services.tools.grandmaster.exposed import (
            GrandmasterExposedTool,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed loading Grandmaster exposed workflow bridge: %s", exc)
        return tuple()

    return tuple(
        GrandmasterExposedTool(tool_id=workflow_id)
        for workflow_id in _workflow_bridge_ids()
    )


def get_all_tools() -> list[Any]:
    """Module-level hook used by python_class module resolution in executor."""

    return list(_workflow_bridge_tools())


@lru_cache(maxsize=1)
def load_tools_catalog() -> Dict[str, Dict[str, Any]]:
    """Load tools_catalog_merged.json as dict keyed by tool name.

    Note: `tools_catalog_merged.json` is a generated artifact and may be gitignored
    in some environments. We merge a small tracked overlay from
    `configs/tools_catalog_overrides.yaml` so critical Python tools remain
    executable via ToolSpec without requiring manual JSON edits.
    """
    path = CONFIGS_DIR / "tools_catalog_merged.json"
    if not path.exists():
        logger.warning(f"Tools catalog not found at {path}")
        data: dict[str, Any] = {}
    else:
        with open(path) as f:
            data = json.load(f)

    merged: Dict[str, Dict[str, Any]] = {t["name"]: t for t in data.get("tools", [])}

    overrides_path = CONFIGS_DIR / "tools_catalog_overrides.yaml"
    if overrides_path.exists():
        try:
            overrides_raw = yaml.safe_load(overrides_path.read_text()) or {}
            tools_raw = overrides_raw.get(
                "tools", overrides_raw if isinstance(overrides_raw, list) else []
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
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load tools_catalog_overrides.yaml: %s", exc)

    return merged


@lru_cache(maxsize=1)
def load_categories() -> Dict[str, Any]:
    """Load tool_categories.yaml."""
    path = CONFIGS_DIR / "tool_categories.yaml"
    if not path.exists():
        logger.warning(f"Tool categories not found at {path}")
        return {}

    with open(path) as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_niwrap_mapping() -> Dict[str, Any]:
    """Load niwrap_mapping.yaml for modalities/intents."""
    path = resolve_mapping_path(
        "niwrap_mapping",
        fallback=CONFIGS_DIR / "catalog" / "niwrap_mapping.yaml",
        must_exist=False,
    )
    if not path.exists():
        logger.warning(f"NiWrap mapping not found at {path}")
        return {}

    with open(path) as f:
        return yaml.safe_load(f) or {}


def resolve_backend(entry: Dict[str, Any]) -> Backend:
    """Map runtime_kind to Backend type."""
    runtime = entry.get("runtime_kind", "python")
    if runtime == "container":
        return "niwrap"
    elif runtime == "mcp":
        return "external_api"
    return "python"


def resolve_category(tool_id: str, categories_config: Dict[str, Any]) -> Optional[str]:
    """Resolve category for a tool using exact matches and pattern rules."""
    # Check exact matches first
    exact_matches = categories_config.get("pattern_matching", {}).get(
        "exact_matches", {}
    )
    if tool_id in exact_matches:
        return exact_matches[tool_id]

    # Check pattern rules
    pattern_rules = categories_config.get("pattern_matching", {}).get(
        "pattern_rules", []
    )
    for rule in pattern_rules:
        pattern = rule.get("pattern", "")
        if pattern and re.match(pattern, tool_id, re.IGNORECASE):
            return rule.get("category")

    return categories_config.get("default_category", "unknown")


def resolve_niwrap_metadata(
    tool_id: str,
    package: str,
    niwrap_map: Dict[str, Any],
) -> tuple[List[str], List[str], Optional[str]]:
    """
    Resolve modalities, intents, and niwrap_id from niwrap_mapping.yaml.

    Returns:
        Tuple of (modalities, intents, niwrap_id)
    """
    defaults = niwrap_map.get("default", {})
    default_modalities = defaults.get("modalities", ["fmri", "smri", "dmri"])
    default_intents = defaults.get("default_intents", ["generic_container_op"])

    # Get package-specific config
    packages = niwrap_map.get("packages", {})
    pkg_config = packages.get(package, {})

    modalities = pkg_config.get("modalities", default_modalities)
    intents: List[str] = list(default_intents)

    # Match rules for intents
    rules = pkg_config.get("rules", [])
    for rule in rules:
        match_str = rule.get("match", "")
        if match_str and match_str.lower() in tool_id.lower():
            rule_intents = rule.get("intents", [])
            # Append rule intents to defaults (dedup)
            intents = list(dict.fromkeys(intents + list(rule_intents)))
            break

    # If still only defaults, allow package default_intents override
    if intents == list(default_intents):
        intents = pkg_config.get("default_intents", default_intents)

    mappings = load_tool_id_mappings()
    runtime_to_catalog = mappings.get("runtime_to_catalog", {})

    niwrap_id: Optional[str] = None
    if ".run" in tool_id:
        niwrap_id = tool_id
    else:
        same_package_candidates: List[str] = []
        fallback_candidates: List[str] = []
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
        # Fall back to the legacy versionless NiWrap-style short id. The
        # NiWrap catalog boundary may still expand this to a versioned
        # descriptor name at lookup time.
        niwrap_id = f"{tool_id}.run"

    return modalities, intents, niwrap_id


def infer_suite_package(tool_id: str) -> Optional[str]:
    """Infer a Neurodesk package family from a canonical runtime tool id."""

    lowered = str(tool_id or "").strip().lower()
    for prefix, package in (
        ("fsl_", "fsl"),
        ("afni_", "afni"),
        ("ants_", "ants"),
        ("freesurfer_", "freesurfer"),
        ("mrtrix3_", "mrtrix"),
        ("workbench_", "workbench"),
    ):
        if lowered.startswith(prefix):
            return package
    return None


def build_toolspec_from_catalog(
    tool_id: str,
    entry: Dict[str, Any],
    categories_config: Dict[str, Any],
    niwrap_map: Dict[str, Any],
) -> ToolSpec:
    """Build ToolSpec from a catalog entry with enrichment from other configs."""
    backend = resolve_backend(entry)

    # Start with catalog values
    modalities = entry.get("modality", [])
    if isinstance(modalities, str):
        modalities = [modalities]
    intents = entry.get("intents") or []
    if isinstance(intents, str):
        intents = [intents]
    niwrap_id = None

    # Enrich NiWrap tools
    if backend == "niwrap":
        package = entry.get("package") or tool_id.split(".")[0]
        niwrap_modalities, niwrap_intents, niwrap_id = resolve_niwrap_metadata(
            tool_id, package, niwrap_map
        )
        # Use niwrap metadata if catalog doesn't have it
        modalities = modalities or niwrap_modalities
        if intents:
            # Merge catalog intents with niwrap intents (dedupe)
            intents = list(dict.fromkeys(intents + niwrap_intents))
        else:
            intents = niwrap_intents
        # niwrap_id from entrypoint or derived
        niwrap_id = entry.get("entrypoint") or niwrap_id
    else:
        # Canonical runtime wrappers such as `fsl_bet` or `ants_registration`
        # are Python-facing, but their search semantics should still inherit the
        # same suite-level Neurodesk metadata as the underlying container tools.
        suite_package = infer_suite_package(tool_id)
        if suite_package:
            niwrap_modalities, niwrap_intents, inferred_niwrap_id = (
                resolve_niwrap_metadata(tool_id, suite_package, niwrap_map)
            )
            modalities = modalities or niwrap_modalities
            if intents:
                intents = list(dict.fromkeys(intents + niwrap_intents))
            else:
                intents = niwrap_intents
            niwrap_id = entry.get("entrypoint") or inferred_niwrap_id

    # Resolve category
    category = entry.get("category") or resolve_category(tool_id, categories_config)

    # Map category to kind
    kind: Optional[Kind] = CATEGORY_TO_KIND.get(category) if category else None

    # Build description (prefer catalog; fallback to id+intents)
    description = (entry.get("description") or "").strip()
    if not description or description.startswith("Tool:"):
        if intents:
            description = f"{tool_id}: " + ", ".join(intents)
        else:
            description = tool_id.replace(".", " ")

    # Resolve python_class path (for python backend).
    #
    # Catalog `function` is typically a capability label (analysis/search/qc),
    # not an importable symbol. Appending it to python_module produces invalid
    # paths such as `...grandmaster.exposed.qc` and breaks tool resolution.
    #
    # Keep python_module as-is and let executor-side module discovery resolve
    # the concrete wrapper by tool id.
    python_class = entry.get("python_module")
    if python_class and tool_id == "datasets.list_resources":
        # Catalog entry omits function name; we know the concrete class
        python_class = f"{python_class}.DatasetResourcesTool"
    if python_class and tool_id == "datasets.describe_resources":
        python_class = f"{python_class}.DatasetDescribeTool"
    if tool_id == "openneuro_download":
        python_class = (
            "brain_researcher.services.tools.archive_tools.OpenNeuroDownloadTool"
        )
    if tool_id == "code_agent":
        python_class = "brain_researcher.services.tools.llm_router_tool.CodingAgentTool"
    if is_workflow_tool_id(tool_id):
        # Workflow IDs are declarative entries bridged through runtime wrappers.
        # Force bridge module to avoid stale catalog python_module paths.
        backend = "python"
        python_class = _WORKFLOW_BRIDGE_MODULE

    # Extract execution_capabilities if present
    execution_capabilities = entry.get("execution_capabilities")
    if not isinstance(execution_capabilities, dict):
        execution_capabilities = None

    qc_spec = normalize_qc_spec(entry.get("qc_spec"))

    runtime_kind = None
    runtime = entry.get("runtime")
    if isinstance(runtime, dict):
        runtime_kind = runtime.get("kind")

    return ToolSpec(
        name=tool_id,
        description=description[:500],
        json_schema={},  # Will be populated when tool is loaded
        backend=backend,
        python_class=python_class,
        niwrap_id=niwrap_id,
        modalities=modalities,
        intents=intents,
        kind=kind,
        search_hint=entry.get("search_hint"),
        allowed_phases=entry.get("allowed_phases") or [],
        approval_level=entry.get("approval_level") or "none",
        consumes=entry.get("consumes", []),
        produces=entry.get("produces", []),
        category=category,
        cost_hint="expensive" if backend == "niwrap" else "normal",
        timeout_s=entry.get("timeout_s"),
        retry_policy=entry.get("retry_policy"),
        idempotent=entry.get("idempotent"),
        side_effects=entry.get("side_effects") or [],
        implementation_level=normalize_implementation_level(
            entry.get("implementation_level"),
            default="production",
        ),
        requires_runtime=infer_requires_runtime(
            entry.get("requires_runtime"),
            backend=backend,
            runtime_kind=str(runtime_kind) if runtime_kind else None,
        ),
        hard_dependencies=normalize_hard_dependencies(entry.get("hard_dependencies")),
        execution_capabilities=execution_capabilities,
        qc_spec=qc_spec,
    )


def build_toolspec_fallback(tool_id: str) -> ToolSpec:
    """
    Build a minimal ToolSpec for tools not in the catalog.

    These are typically high-level service clients like neurokg.client.
    """
    # Infer backend and kind from tool_id patterns
    backend: Backend = "python"
    kind: Optional[Kind] = None
    intents: List[str] = []
    modalities: List[str] = []
    niwrap_id: Optional[str] = None
    python_class: Optional[str] = None

    tool_lower = tool_id.lower()

    if tool_lower.startswith("mcp."):
        backend = "external_api"
        kind = "data"
        intents = ["mcp_tool"]
        return ToolSpec(
            name=tool_id,
            description=f"{tool_id} (MCP tool)",
            json_schema={},
            backend=backend,
            python_class=None,
            niwrap_id=None,
            modalities=[],
            intents=intents,
            kind=kind,
            consumes=[],
            produces=[],
            category="mcp",
            cost_hint="normal",
            timeout_s=None,
            retry_policy=None,
            idempotent=None,
            side_effects=[],
        )

    # Known Python tool wrappers where the exposed tool ID maps to a module that
    # contains one or more NeuroToolWrapper implementations.
    # (Executor can resolve module -> correct tool instance by name.)
    _KNOWN_PYTHON_MODULES: dict[str, tuple[str, Kind, list[str], list[str]]] = {
        # Nilearn analysis
        "glm_first_level": (
            "brain_researcher.services.tools.nilearn_glm",
            "analysis",
            ["fmri"],
            ["glm_first_level_fmri"],
        ),
        "glm_second_level": (
            "brain_researcher.services.tools.nilearn_glm",
            "analysis",
            ["fmri"],
            ["glm_second_level_group"],
        ),
        "connectivity_matrix": (
            "brain_researcher.services.tools.nilearn_connectivity",
            "analysis",
            ["fmri"],
            ["connectivity_analysis"],
        ),
        "seed_based_fc": (
            "brain_researcher.services.tools.nilearn_connectivity",
            "analysis",
            ["fmri"],
            ["seed_based_connectivity"],
        ),
        "viz_stat_maps": (
            "brain_researcher.services.tools.nilearn_viz",
            "viz",
            ["fmri", "smri"],
            ["visualization", "fmri_visualization"],
        ),
        "surface_projection": (
            "brain_researcher.services.tools.nilearn_viz",
            "viz",
            ["fmri", "smri"],
            ["visualization", "surface_ops"],
        ),
        # Pipelines / planning helpers
        "pipeline.search": (
            "brain_researcher.services.tools.pipeline_search_tool",
            "analysis",
            ["fmri", "smri", "dmri"],
            ["pipeline_search"],
        ),
        # FreeSurfer (python backend generating scripts)
        "freesurfer_recon_all": (
            "brain_researcher.services.tools.freesurfer_tool",
            "imaging",
            ["smri"],
            ["cortical_reconstruction"],
        ),
        # Stubs / lightweight helpers
        "extract_timeseries": (
            "brain_researcher.services.tools.extract_timeseries_tool",
            "analysis",
            ["fmri"],
            ["roi_timeseries_fmri"],
        ),
        "fetch_atlas": (
            "brain_researcher.services.tools.fetch_atlas_tool",
            "data",
            ["fmri", "smri", "dmri"],
            ["fetch_atlas_parcellation"],
        ),
    }
    if tool_lower in _KNOWN_PYTHON_MODULES:
        python_class, kind, modalities, intents = _KNOWN_PYTHON_MODULES[tool_lower]
        backend = "python"

    # Knowledge graph tools
    if any(kw in tool_lower for kw in ["neurokg", "graph", "concept", "coordinate"]):
        kind = "kg"
        intents = ["knowledge_graph_query"]
    # External API tools
    elif any(kw in tool_lower for kw in ["gemini", "openai", "claude"]):
        backend = "external_api"
        kind = "analysis"
        intents = ["llm_query"]
    # Dataset tools
    elif any(kw in tool_lower for kw in ["dataset", "openneuro", "data"]):
        kind = "data"
        intents = ["data_access"]
        if tool_lower == "openneuro_download":
            python_class = (
                "brain_researcher.services.tools.archive_tools.OpenNeuroDownloadTool"
            )
    # Multiple-comparison correction (pure python)
    elif tool_lower == "multiple_comparison_correction":
        kind = "analysis"
        intents = ["statistical_inference", "multiple_comparison_correction"]
        python_class = "brain_researcher.services.tools.multiple_comparison_tool.MultipleComparisonTool"
    # Meta-analysis tools
    elif "meta_analysis" in tool_lower:
        kind = "meta"
        intents = ["meta_analysis"]
    # Visualization tools
    elif "viz" in tool_lower:
        kind = "viz"
        intents = ["visualization"]
        # Provide python_class for known nilearn viz wrappers so execution
        # does not fail with "No python_class defined" during pipeline runs.
        if tool_lower == "viz_stat_maps":
            python_class = "brain_researcher.services.tools.nilearn_viz.VizStatMapTool"
        elif tool_lower == "surface_projection":
            python_class = (
                "brain_researcher.services.tools.nilearn_viz.SurfaceProjectionTool"
            )
        else:
            python_class = None
    # Connectivity tools
    elif "connectivity" in tool_lower:
        kind = "analysis"
        modalities = ["fmri"]
        intents = ["connectivity_analysis"]
    # Literature tools
    elif "literature" in tool_lower:
        kind = "meta"
        intents = ["literature_search"]
    # Advanced analysis
    elif "advanced_analysis" in tool_lower:
        kind = "analysis"
        modalities = ["fmri", "smri"]
        intents = ["advanced_analysis"]
    # FSL tools (NiWrap-backed imaging)
    elif tool_lower.startswith("fsl."):
        backend = "niwrap"
        kind = "imaging"
        modalities = ["fmri", "smri"]
        niwrap_id = f"{tool_id}.run"
        # Infer intents from tool name
        if "bet" in tool_lower:
            intents = ["skull_strip_mri"]
        elif "flirt" in tool_lower:
            intents = ["linear_registration"]
        elif "fnirt" in tool_lower:
            intents = ["nonlinear_registration", "registration_to_mni"]
        elif "feat" in tool_lower:
            intents = ["fmri_glm_analysis"]
            modalities = ["fmri"]
        elif "melodic" in tool_lower:
            intents = ["ica_decomposition"]
            modalities = ["fmri"]
        elif "bedpostx" in tool_lower:
            intents = ["diffusion_modeling", "dmri_tractography"]
            modalities = ["dmri"]
        elif "palm" in tool_lower:
            intents = ["permutation_testing"]
        elif "fix" in tool_lower:
            intents = ["ica_denoising"]
            modalities = ["fmri"]
        else:
            intents = ["fsl_processing"]
    # AFNI tools (NiWrap-backed imaging)
    elif tool_lower.startswith("afni."):
        backend = "niwrap"
        kind = "imaging"
        modalities = ["fmri", "smri"]
        niwrap_id = f"{tool_id}.run"
        if "clustsim" in tool_lower:
            intents = ["afni_clustsim_correction"]
        elif "deconvolve" in tool_lower:
            intents = ["fmri_glm_analysis"]
            modalities = ["fmri"]
        else:
            intents = ["afni_processing"]
    # ANTs tools (NiWrap-backed imaging)
    elif tool_lower.startswith("ants."):
        backend = "niwrap"
        kind = "imaging"
        modalities = ["fmri", "smri"]
        niwrap_id = f"{tool_id}.run"
        intents = ["ants_registration"]
    # FreeSurfer tools (NiWrap-backed imaging)
    elif tool_lower.startswith("freesurfer."):
        backend = "niwrap"
        kind = "imaging"
        modalities = ["smri"]
        niwrap_id = f"{tool_id}.run"
        intents = ["cortical_reconstruction"]
    # Declarative workflows are runtime-registered wrappers. Point to this
    # module so executor module-resolution can pick the matching wrapper.
    if not python_class and is_workflow_tool_id(tool_id):
        kind = kind or "analysis"
        intents = intents or ["workflow"]
        python_class = _WORKFLOW_BRIDGE_MODULE

    # Create human-readable name from tool_id
    name_parts = tool_id.replace(".", " ").replace("_", " ").title()
    description = f"{tool_id}: " + ", ".join(intents) if intents else name_parts

    return ToolSpec(
        name=tool_id,
        description=description[:500],
        json_schema={},
        backend=backend,
        python_class=python_class or locals().get("python_class"),
        niwrap_id=niwrap_id,
        modalities=modalities,
        intents=intents,
        kind=kind,
        search_hint=None,
        allowed_phases=[],
        approval_level="none",
        consumes=[],
        produces=[],
        category=None,
        cost_hint="expensive" if backend == "niwrap" else "normal",
    )


def load_tool_specs(
    force_reload: bool = False,
    exposed_only: bool = True,
    include_workflows: bool = False,
    agent_visible_only: bool = True,
) -> List[ToolSpec]:
    """
    Load ToolSpecs as a unified list.

    This is the main entry point for getting tool specifications.

    Args:
        force_reload: If True, clear caches and reload from disk
        exposed_only: If True, load curated exposed tools only; otherwise load all
            catalog entries.
        include_workflows: If True, include workflow IDs in returned ToolSpecs.
        agent_visible_only: When True, hide local-first blocked tools from exposed
            views. When False, keep the full exposed discovery surface.

    Returns:
        List of ToolSpec objects
    """
    if force_reload:
        load_exposed_tools.cache_clear()
        load_orchestration_workflows.cache_clear()
        load_workflow_catalog_ids.cache_clear()
        load_tool_id_mappings.cache_clear()
        load_tools_catalog.cache_clear()
        load_categories.cache_clear()
        load_niwrap_mapping.cache_clear()

    catalog = load_tools_catalog()
    categories = load_categories()
    niwrap_map = load_niwrap_mapping()
    exposed = (
        load_exposed_tools(agent_visible_only=agent_visible_only)
        if exposed_only
        else None
    )
    alias_map = get_exposed_alias_map()

    specs: List[ToolSpec] = []
    if exposed_only:
        tool_ids = list(exposed or [])
    else:
        tool_ids = sorted(catalog.keys())

    # Keep workflow inclusion symmetric across exposed/all views so
    # search-time discoverability and execute-time resolution agree.
    if include_workflows:
        workflow_ids = sorted(
            set(load_orchestration_workflows()) | set(load_workflow_catalog_ids())
        )
        if exposed_only and agent_visible_only:
            workflow_ids = _filter_agent_visible_tool_ids(workflow_ids)
        tool_ids.extend(workflow_ids)

    # Preserve order while deduplicating.
    tool_ids = list(dict.fromkeys(tool_ids))
    if not include_workflows:
        tool_ids = [tool_id for tool_id in tool_ids if not is_workflow_tool_id(tool_id)]

    for tool_id in tool_ids:
        catalog_id = resolve_catalog_tool_id(
            tool_id,
            exposed_only=exposed_only,
            alias_map=alias_map,
        )
        if catalog_id in catalog:
            entry = catalog[catalog_id]
            spec = build_toolspec_from_catalog(tool_id, entry, categories, niwrap_map)
        else:
            logger.debug(
                f"Tool '{tool_id}' not in catalog (lookup '{catalog_id}'), using fallback"
            )
            spec = build_toolspec_fallback(tool_id)

        specs.append(spec)

    mode = "exposed" if exposed_only else "all"
    if include_workflows:
        mode += "+workflows"
    logger.info("Loaded %d %s tool specifications", len(specs), mode)
    return specs


def get_toolspec_by_name(name: str) -> Optional[ToolSpec]:
    """Get a single ToolSpec by name."""
    primary_specs = load_tool_specs(include_workflows=True)
    for spec in primary_specs:
        if spec.name == name:
            return spec

    discoverable_specs = load_tool_specs(
        include_workflows=True,
        agent_visible_only=False,
    )
    for spec in discoverable_specs:
        if spec.name == name:
            return spec

    # Also allow alias lookup by mapped catalog id for callers that pass the
    # internal id instead of exposed id.
    alias_map = get_exposed_alias_map()
    reverse_alias = {v: k for k, v in alias_map.items()}
    alias_name = reverse_alias.get(name)
    if alias_name:
        for spec in discoverable_specs:
            if spec.name == alias_name:
                return spec
    return None


# Convenience function for quick access
def list_exposed_tool_names() -> List[str]:
    """Get list of all exposed tool names."""
    return load_exposed_tools()
