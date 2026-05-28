"""Enhanced tool catalog loader with support for containerized tools.

Active runtime planning is catalog-only. The legacy branch remains here only for
compatibility helpers and internal tests while legacy Python tool metadata is
still merged into the catalog path.
"""

from __future__ import annotations

import json
import logging
import os
import re
import yaml
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# NiWrap MCP catalog support removed; keep placeholder for compatibility
iter_tool_definitions = None

from pydantic import BaseModel, Field, field_validator, ConfigDict

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import get_repo_root as get_shared_repo_root
from brain_researcher.services.shared.planner.models import (
    Domain,
    Modality,
    ResourceType,
)
from brain_researcher.services.tools.catalog_loader import (
    resolve_primary_runtime_tool_id,
    resolve_runtime_tool_ids as resolve_runtime_registry_tool_ids,
)
from .intents import Intent

logger = logging.getLogger(__name__)


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


@lru_cache(maxsize=8192)
def _preferred_runtime_aliases(tool_id: str) -> List[str]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        return []

    primary = resolve_primary_runtime_tool_id(normalized)
    if primary:
        if primary == normalized:
            return _dedupe_preserve_order(
                [primary, *resolve_runtime_registry_tool_ids(normalized, include_self=False)]
            )
        return _dedupe_preserve_order(
            [primary, *resolve_runtime_registry_tool_ids(normalized, include_self=False)]
        )

    return _dedupe_preserve_order(resolve_runtime_registry_tool_ids(normalized, include_self=False))


def _filter_local_first_capabilities(
    tools: List["ToolCapability"],
    *,
    include_local_first: bool = False,
) -> List["ToolCapability"]:
    """Hide remote execution tools from agent-facing planner search by default."""

    if include_local_first:
        return list(tools)

    try:
        from brain_researcher.services.agent.tool_allowlist_loader import (
            is_local_first_blocked_tool,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to import planner local-first filter: %s", exc)
        return list(tools)

    return [tool for tool in tools if not is_local_first_blocked_tool(tool.id)]


# ========================================
# Pydantic Models
# ========================================


class ResourceSpec(BaseModel):
    """Resource requirements for a tool."""

    cpu_min: int = Field(..., ge=1, le=32)
    mem_mb_min: int = Field(..., ge=128, le=131072)
    gpu: bool = False
    time_min_default: float = Field(..., ge=0, le=2880)
    scaling_hints: List[Dict[str, Any]] = Field(default_factory=list)


class ContainerSpec(BaseModel):
    """Container execution configuration."""

    package_ref: str  # Reference to niwrap_containers.yaml
    runtime: str  # apptainer, singularity, docker
    image: Optional[str] = None  # Usually loaded from niwrap_containers.yaml
    image_is_directory: bool = True
    binds: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    network_disabled: bool = True
    require_license: bool = False


class PythonRunnerSpec(BaseModel):
    """Python function/class execution configuration."""

    module: str  # e.g., "brain_researcher.core.analysis.connectivity"
    function: str  # e.g., "compute_connectivity_matrix"
    entry_type: str = "function"  # or "class"


class ToolMetadata(BaseModel):
    """Tool metadata (docs, citations, etc.)."""

    description: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    literature: List[str] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)


class ToolCapability(BaseModel):
    """Full tool capability specification (hybrid: container + python tools)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    package: str
    description: Optional[str] = None
    documentation: Optional[str] = None
    runtime_kind: str  # "container" or "python"
    entrypoint: Optional[str] = None  # NiWrap tool ID (container only)
    modality: List[str]  # Using str to be flexible during load
    capabilities: List[str]  # Capability tags (e.g., "skull_strip", "registration")
    intents: List[str] = Field(
        default_factory=list
    )  # Intent ids implemented by this tool
    consumes: List[str]  # Resource types
    produces: List[str]  # Resource types
    resources: ResourceSpec
    container: Optional[ContainerSpec] = None  # Only for runtime_kind="container"
    python: Optional[PythonRunnerSpec] = None  # Only for runtime_kind="python"
    metadata: Optional[ToolMetadata] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None  # "catalog" or "legacy" (for hybrid merge tracking)

    @field_validator("id")
    def validate_id(cls, v: str):
        """Allow both legacy planner IDs and runtime-canonical tool names."""
        normalized = str(v or "").strip()
        if not normalized:
            raise ValueError("Tool ID must be non-empty")
        if re.search(r"\s", normalized):
            raise ValueError(f"Tool ID contains unsupported characters: {v}")
        return v

    @field_validator("runtime_kind")
    def validate_runtime(cls, v: str):
        """Ensure runtime_kind is valid."""
        if v not in ["container", "python", "mcp"]:
            raise ValueError(
                f"runtime_kind must be 'container', 'python', or 'mcp', got: {v}"
            )
        return v

    @field_validator("modality", mode="before")
    @classmethod
    def normalize_modality_list(cls, v: List[str]) -> List[str]:
        from brain_researcher.services.shared.planner.models import normalize_modality

        normed: List[str] = []
        for m in v or []:
            normed.append(normalize_modality(m))
        return normed


class ToolSpec(BaseModel):
    """Legacy tool specification (from tools_catalog.json)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    domain: Domain
    modality: List[Modality]
    consumes: Dict[str, str]
    produces: Dict[str, str]
    constraints: Dict[str, Any] = Field(default_factory=dict)
    runtime_kind: str = Field(
        default="container", description="Execution backend (container or python)"
    )
    python_module: Optional[str] = Field(
        default=None, description="Python module path for python runtime"
    )
    python_function: Optional[str] = Field(
        default=None, description="Callable name for python runtime"
    )
    intents: List[str] = Field(default_factory=list)

    @field_validator("consumes", "produces", mode="before")
    @classmethod
    def _validate_resources(cls, v: Dict[str, str]) -> Dict[str, str]:
        validated = {}
        for key, val in (v or {}).items():
            validated[key] = ResourceType.validate(val)
        return validated


class CapabilityIndex(BaseModel):
    """Indexes for fast tool lookup."""

    by_id: Dict[str, ToolCapability] = Field(default_factory=dict)
    by_alias: Dict[str, str] = Field(default_factory=dict)  # alias -> canonical tool ID
    by_capability: Dict[str, List[str]] = Field(
        default_factory=dict
    )  # capability -> tool IDs
    by_modality: Dict[str, List[str]] = Field(
        default_factory=dict
    )  # modality -> tool IDs
    by_package: Dict[str, List[str]] = Field(
        default_factory=dict
    )  # package -> tool IDs
    by_resource_type: Dict[str, List[str]] = Field(
        default_factory=dict
    )  # resource -> tool IDs
    by_intent: Dict[str, List[str]] = Field(default_factory=dict)  # intent -> tool IDs


# ========================================
# Configuration
# ========================================


def get_planner_source() -> str:
    """Get planner source from environment for loader compatibility.

    Returns:
        Planner source: "catalog" (default) or "legacy"

    Active planner HTTP surfaces ignore legacy mode and always run catalog mode.
    This env switch is retained only for loader compatibility and tests.
    """
    return os.environ.get("BR_PLANNER_SOURCE", "catalog").lower()


def get_repo_root() -> Path:
    """Get repository root directory."""
    return get_shared_repo_root()


_ALLOWED_LEGACY_DOMAINS = set(Domain.__args__)
_ALLOWED_LEGACY_MODALITIES = set(Modality.__args__)


def _resolve_tools_catalog_path(path: Optional[Path] = None) -> Path:
    """Resolve the planner's legacy tool catalog with merged fallback."""

    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"Tool catalog not found at {path}")
        return path

    repo_root = get_repo_root()
    legacy_path = repo_root / "configs" / "tools_catalog.json"
    if legacy_path.exists():
        return legacy_path

    merged_path = repo_root / "configs" / "tools_catalog_merged.json"
    if merged_path.exists():
        return merged_path

    raise FileNotFoundError(
        f"Tool catalog not found at {legacy_path} or {merged_path}"
    )


def _infer_legacy_domain(raw_domain: Any, name: str, tags: List[str]) -> str:
    """Map merged-catalog domains onto the legacy planner domain contract."""

    domain = str(raw_domain or "").strip().lower()
    if domain in _ALLOWED_LEGACY_DOMAINS:
        return domain

    blob = " ".join([domain, name.lower(), *[str(tag).lower() for tag in tags]])
    if any(token in blob for token in ("literature", "pubmed", "paper", "citation")):
        return "literature"
    if any(token in blob for token in ("gene", "genetic")):
        return "neurogenetics"
    if "clinical" in blob:
        return "clinical"
    if any(token in blob for token in ("kg", "knowledge graph", "knowledge_graph")):
        return "neurokg"
    if "llm" in blob:
        return "llm_service"
    return "neuroimaging"


def _infer_legacy_modalities(raw_domain: Any, name: str, tags: List[str]) -> List[str]:
    """Infer a legacy modality list from merged-catalog metadata."""

    blob = " ".join([str(raw_domain or ""), name, *tags]).lower()
    inferred: List[str] = []
    for modality, patterns in (
        ("fmri", ("fmri", "bold")),
        ("dmri", ("dmri", "diffusion")),
        ("smri", ("smri", "structural", "anatomical")),
        ("eeg", ("eeg",)),
        ("meg", ("meg",)),
        ("ieeg", ("ieeg",)),
        ("pet", ("pet",)),
        ("genetics", ("genetic", "gene")),
        ("multimodal", ("multimodal",)),
        ("optical", ("optical",)),
        ("clinical", ("clinical",)),
        ("literature", ("literature", "pubmed", "paper", "citation")),
        ("data_catalog", ("dataset", "catalog")),
        ("rag", ("rag",)),
        ("search", ("search", "query")),
    ):
        if any(pattern in blob for pattern in patterns):
            inferred.append(modality)

    if not inferred:
        inferred.append("general")

    return inferred


def _tool_spec_from_merged_entry(entry: Dict[str, Any]) -> Optional[ToolSpec]:
    """Coerce a merged-catalog entry into the legacy ToolSpec shape."""

    name = entry.get("name")
    if not name:
        return None

    tags = [str(tag).strip().lower() for tag in entry.get("tags") or [] if tag]
    try:
        return ToolSpec(
            name=name,
            domain=_infer_legacy_domain(entry.get("domain"), name, tags),
            modality=_infer_legacy_modalities(entry.get("domain"), name, tags),
            consumes={},
            produces={},
            constraints=entry.get("constraints") or {},
            runtime_kind=entry.get("runtime_kind") or "python",
            python_module=entry.get("python_module"),
            python_function=entry.get("python_function") or name,
            intents=entry.get("intents") or [],
        )
    except Exception as exc:
        logger.warning("Skipping merged catalog entry %s: %s", name, exc)
        return None


# ========================================
# Loaders
# ========================================


def load_capabilities_yaml(
    path: Optional[Path] = None,
    generated_paths: Optional[List[Path]] = None,
    source: Optional[str] = None,
) -> List[ToolCapability]:
    """Load curated catalog plus optional generated catalogs.

    Defaults to `capabilities.merged.yaml` (2073 tools). Env override:
    BR_CAPABILITIES_SOURCE=merged|yaml. Curated entries win on ID conflicts.
    Generated entries are tagged source="catalog_generated".
    """

    source = source or os.getenv("BR_CAPABILITIES_SOURCE", "merged").lower()

    if path is None:
        catalog_dir = get_repo_root() / "configs" / "catalog"
        if source == "merged":
            merged = catalog_dir / "capabilities.merged.yaml"
            path = merged if merged.exists() else catalog_dir / "capabilities.yaml"
        else:
            path = catalog_dir / "capabilities.yaml"

    if not path.exists():
        raise FileNotFoundError(f"Capabilities catalog not found at {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tools_by_id: Dict[str, ToolCapability] = {}
    for tool_data in data.get("tools", []):
        tool_data["source"] = "catalog"
        tool = ToolCapability(**tool_data)
        tools_by_id[tool.id] = tool

    for gen_path in generated_paths or []:
        if not gen_path.exists():
            continue
        with gen_path.open("r", encoding="utf-8") as f:
            gen_data = yaml.safe_load(f) or {}
        for tool_data in gen_data.get("tools", []):
            tool_id = tool_data.get("id")
            if not tool_id or tool_id in tools_by_id:
                continue
            tool_data["source"] = "catalog_generated"
            try:
                tools_by_id[tool_id] = ToolCapability(**tool_data)
            except Exception:
                # Skip malformed generated entries silently; they can be regenerated
                continue

    return list(tools_by_id.values())


def load_tools_catalog_json(path: Optional[Path] = None) -> Dict[str, ToolSpec]:
    """Load legacy tool catalog from JSON.

    Args:
        path: Optional path to tools_catalog.json or tools_catalog_merged.json.

    Returns:
        Dict mapping tool name to ToolSpec
    """
    path = _resolve_tools_catalog_path(path)

    def _load_entries(source_path: Path) -> tuple[list[dict[str, Any]], bool]:
        with source_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        entries = raw.get("tools", [])
        is_legacy_schema = bool(entries) and "consumes" in entries[0] and "produces" in entries[0]
        return entries, is_legacy_schema

    tools: Dict[str, ToolSpec] = {}

    entries, is_legacy_schema = _load_entries(path)
    if is_legacy_schema:
        for entry in entries:
            spec = ToolSpec(**entry)
            tools[spec.name] = spec
    else:
        for entry in entries:
            spec = _tool_spec_from_merged_entry(entry)
            if spec is None:
                continue
            tools[spec.name] = spec

    merged_path = get_repo_root() / "configs" / "tools_catalog_merged.json"
    if merged_path.exists() and merged_path != path:
        merged_entries, _ = _load_entries(merged_path)
        for entry in merged_entries:
            spec = _tool_spec_from_merged_entry(entry)
            if spec is None or spec.name in tools:
                continue
            tools[spec.name] = spec

    return tools


def load_tool_resources(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load tool resource requirements from YAML.

    Args:
        path: Optional path to tool_resources.yaml

    Returns:
        Dict mapping tool ID to resource spec
    """
    if path is None:
        path = get_repo_root() / "configs" / "tool_resources.yaml"

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("tools", {})


def load_niwrap_containers(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load container configuration from YAML.

    Args:
        path: Optional path to niwrap_containers.yaml

    Returns:
        Dict mapping package name to container config
    """
    if path is None:
        path = get_repo_root() / "configs" / "niwrap_containers.yaml"

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_niwrap_mapping(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load NiWrap prefix/intents mapping."""
    if path is None:
        path = resolve_mapping_path(
            "niwrap_mapping",
            fallback=get_repo_root() / "configs" / "catalog" / "niwrap_mapping.yaml",
            must_exist=False,
        )
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_tool_categories(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load tool categories from YAML.

    Args:
        path: Optional path to tool_categories.yaml

    Returns:
        Dict with category information
    """
    if path is None:
        path = get_repo_root() / "configs" / "tool_categories.yaml"

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ========================================
# Enrichment and Merging
# ========================================


def _map_intents_for_niwrap(
    name: str, package: str, mapping: Dict[str, Any]
) -> Tuple[List[str], List[str]]:
    """Infer intents and modalities from mapping rules."""
    default = mapping.get("default", {})
    modalities = default.get("modalities", [])
    intents: List[str] = []

    pkg_rules = (mapping.get("packages") or {}).get(package, {})
    if pkg_rules.get("modalities"):
        modalities = pkg_rules["modalities"]

    rules = pkg_rules.get("rules", [])
    lname = name.lower()
    for rule in rules:
        match = str(rule.get("match", "")).lower()
        if match and match in lname:
            intents = rule.get("intents", []) or []
            break

    if not intents:
        intents = pkg_rules.get("default_intents") or default.get("default_intents", [])

    return intents, modalities


def load_niwrap_capabilities(
    mapping: Dict[str, Any], containers: Dict[str, Dict[str, Any]]
) -> List[ToolCapability]:
    """Dynamically convert NiWrap tool definitions into ToolCapability entries."""
    if iter_tool_definitions is None:
        return []

    tools: List[ToolCapability] = []
    limit_env = os.environ.get("BR_NIWRAP_LIMIT")
    limit = int(limit_env) if limit_env else None

    count = 0
    for tool_def in iter_tool_definitions():
        if limit and count >= limit:
            break
        name = tool_def.get("name")
        if not name or not name.endswith(".run"):
            continue
        meta = tool_def.get("metadata", {}) or {}
        package = meta.get("package") or name.split(".")[0]

        intents, modalities = _map_intents_for_niwrap(name, package, mapping)
        container = meta.get("container", {}) or {}
        package_ref = package
        entrypoint = name

        # Build resources from metadata if present
        res_meta = meta.get("resources") or {}
        cpu_min = (
            int(res_meta.get("cpu_cores", {}).get("default", 1))
            if isinstance(res_meta.get("cpu_cores"), dict)
            else 1
        )
        mem_gb = res_meta.get("memory_gb", {})
        mem_mb_min = (
            int(float(mem_gb.get("recommended", mem_gb.get("min", 2.0))) * 1024)
            if isinstance(mem_gb, dict)
            else 2048
        )
        time_min_default = 5

        cap = ToolCapability(
            id=f"container.{name}",
            name=name.replace(".", " "),
            package=package,
            runtime_kind="container",
            entrypoint=entrypoint,
            modality=modalities or ["fmri", "smri"],
            capabilities=[package],  # coarse package tag
            intents=intents,
            consumes=[],
            produces=[],
            resources=ResourceSpec(
                cpu_min=cpu_min,
                mem_mb_min=mem_mb_min,
                gpu=False,
                time_min_default=time_min_default,
            ),
            container=ContainerSpec(
                package_ref=package_ref,
                runtime=container.get("type") or "apptainer",
                image=container.get("image"),
                image_is_directory=False,
                binds=[],
                env={},
                network_disabled=False,
            ),
            metadata=ToolMetadata(
                description=tool_def.get("description"),
                authors=[],
                literature=[],
                urls=[],
            ),
            constraints={},
            source="catalog_generated",
        )
        tools.append(cap)
        count += 1

    return tools


def legacy_tool_to_capability(name: str, spec: ToolSpec) -> ToolCapability:
    """Convert legacy ToolSpec (from tools_catalog.json) to ToolCapability.

    Args:
        name: Tool name from tools_catalog.json
        spec: ToolSpec from tools_catalog.json

    Returns:
        ToolCapability with runtime_kind="python"
    """
    tool_id = resolve_primary_runtime_tool_id(name) or name
    runtime_kind = str(spec.runtime_kind or "python")

    # Convert modality list to strings
    modality_list = [str(m) for m in spec.modality]

    # Convert consumes/produces from Dict[str, ResourceType] to List[str]
    consumes_list = list(spec.consumes.values())
    produces_list = list(spec.produces.values())

    # Extract default resources or use sensible defaults
    cpu_min = spec.constraints.get("cpu_min", 1)
    mem_mb_min = spec.constraints.get("mem_mb_min", 512)
    gpu = spec.constraints.get("gpu", False)
    time_min_default = spec.constraints.get("time_min_default", 5.0)

    # Build resources spec
    resources = ResourceSpec(
        cpu_min=cpu_min,
        mem_mb_min=mem_mb_min,
        gpu=gpu,
        time_min_default=time_min_default,
    )

    # Create Python runner spec (even if legacy didn't provide explicit module/function)
    if runtime_kind == "python" and not spec.python_module:
        spec.python_module = f"brain_researcher.services.{spec.domain}"
    if runtime_kind == "python" and not spec.python_function:
        spec.python_function = name
    python_spec = None
    if runtime_kind == "python":
        python_spec = PythonRunnerSpec(
            module=spec.python_module,
            function=spec.python_function,
            entry_type="function",
        )

    package = (
        tool_id.split(".", 1)[0]
        if "." in tool_id
        else (tool_id.split("_", 1)[0] if "_" in tool_id else runtime_kind)
    )
    container_spec = None
    if runtime_kind == "container":
        container_spec = ContainerSpec(package_ref=package, runtime="apptainer")

    # Infer capability tags from tool name and domain
    capabilities = []
    if "extract" in name.lower():
        capabilities.append("extraction")
    if "connectivity" in name.lower():
        capabilities.append("connectivity")
    if "meta" in name.lower():
        capabilities.append("meta_analysis")
    if "search" in name.lower():
        capabilities.append("search")
    if "query" in name.lower():
        capabilities.append("query")
    if not capabilities:
        capabilities.append(spec.domain)  # Fallback to domain

    return ToolCapability(
        id=tool_id,
        name=name.replace("_", " ").title(),
        package=package,
        runtime_kind=runtime_kind,
        entrypoint=None,
        modality=modality_list,
        capabilities=capabilities,
        consumes=consumes_list,
        produces=produces_list,
        resources=resources,
        container=container_spec,
        python=python_spec,
        constraints=spec.constraints,
        source="legacy",  # Tag as legacy tool
    )


def enrich_tool_with_container_info(
    tool: ToolCapability, containers: Dict[str, Dict[str, Any]]
) -> ToolCapability:
    """Enrich tool with container info from niwrap_containers.yaml.

    Args:
        tool: ToolCapability to enrich
        containers: Container config dict

    Returns:
        Enriched ToolCapability
    """
    package_ref = tool.container.package_ref
    if package_ref in containers:
        container_info = containers[package_ref]
        # Only update if not already set
        if not tool.container.image:
            tool.container.image = container_info.get("image")
        if not tool.container.binds:
            tool.container.binds = container_info.get("binds", [])
        if not tool.container.env:
            tool.container.env = container_info.get("env", {})
        if "network_disabled" in container_info:
            tool.container.network_disabled = container_info["network_disabled"]
        if "require_license" in container_info:
            tool.container.require_license = container_info["require_license"]
        if "image_is_directory" in container_info:
            tool.container.image_is_directory = container_info["image_is_directory"]

    return tool


def enrich_and_merge(
    capabilities: List[ToolCapability],
    legacy_tools: Dict[str, ToolSpec],
    resources: Dict[str, Dict[str, Any]],
    mapping: Optional[Dict[str, Any]] = None,
    containers: Dict[str, Dict[str, Any]] = None,
    merge_legacy: bool = True,
    include_niwrap: bool = True,
) -> List[ToolCapability]:
    """Merge capabilities catalog with legacy tools and enrich with metadata.

    Strategy:
    1. Enrich capabilities entries with container info
    2. Convert legacy tools to ToolCapability format (if merge_legacy=True)
    3. Merge, with container tools winning on ID conflicts

    Args:
        capabilities: Tools from capabilities.yaml (source="catalog")
        legacy_tools: Tools from tools_catalog.json
        resources: Resource requirements
        containers: Container configurations
        merge_legacy: Whether to include legacy tools (default: True, overridden by BR_PLANNER_INCLUDE_LEGACY)

    Returns:
        Merged list of ToolCapability objects
    """
    # Fail fast on duplicates inside curated catalog (capabilities.yaml)
    seen_catalog_ids: Set[str] = set()
    dup_catalog_ids: Set[str] = set()
    for tool in capabilities:
        if tool.id in seen_catalog_ids:
            dup_catalog_ids.add(tool.id)
        seen_catalog_ids.add(tool.id)
    if dup_catalog_ids:
        raise ValueError(
            f"Duplicate tool IDs in catalog capabilities: {sorted(dup_catalog_ids)}"
        )

    if mapping is None:
        mapping = {}
    if containers is None:
        containers = {}

    # 1. Enrich containerized tools with container info
    enriched_container = []
    for tool in capabilities:
        # normalize description/documentation from metadata if not already set
        if tool.description is None and tool.metadata and tool.metadata.description:
            tool.description = tool.metadata.description
        if tool.documentation is None and tool.metadata and tool.metadata.urls:
            tool.documentation = tool.metadata.urls[0]

        if tool.runtime_kind == "container" and tool.container:
            enriched_container.append(enrich_tool_with_container_info(tool, containers))
        else:
            enriched_container.append(tool)

    # 2. Convert legacy Python tools to ToolCapability format
    # BR_PLANNER_INCLUDE_LEGACY remains the only public override for this merge path.
    env_include = os.environ.get("BR_PLANNER_INCLUDE_LEGACY")
    if env_include is not None:
        merge_legacy = env_include.lower() == "true"

    env_niwrap = os.environ.get("BR_PLANNER_INCLUDE_NIWRAP")
    if env_niwrap is not None:
        include_niwrap = env_niwrap.lower() == "true"

    legacy_as_capabilities = []
    if merge_legacy:
        # detect duplicates in legacy map first
        dup_legacy_ids = [
            name
            for name in legacy_tools.keys()
            if list(legacy_tools.keys()).count(name) > 1
        ]
        if dup_legacy_ids:
            logger.warning(
                "Duplicate legacy tool names found (first occurrence will be used): %s",
                sorted(set(dup_legacy_ids)),
            )
        for name, spec in legacy_tools.items():
            try:
                legacy_capability = legacy_tool_to_capability(name, spec)
                legacy_as_capabilities.append(legacy_capability)
            except Exception as e:
                # Log warning but continue - don't fail entire merge for one bad tool
                logger.warning(f"Failed to convert legacy tool {name}: {e}")
                continue

    # 3. Merge with conflict resolution: container (catalog) tools win on ID conflicts
    # Build dict by ID from catalog tools first (these have priority)
    tools_by_id: Dict[str, ToolCapability] = {}
    for tool in enriched_container:
        tools_by_id[tool.id] = tool

    # Add legacy tools only if ID doesn't already exist
    conflicts = []
    for tool in legacy_as_capabilities:
        if tool.id in tools_by_id:
            conflicts.append(tool.id)
            logger.debug(
                f"Skipping legacy tool {tool.id} - catalog tool with same ID exists (container wins)"
            )
        else:
            tools_by_id[tool.id] = tool

    # 4. Add NiWrap-generated tools if requested
    if include_niwrap:
        niwrap_tools = load_niwrap_capabilities(mapping, containers)
        for tool in niwrap_tools:
            if tool.id in tools_by_id:
                continue
            tools_by_id[tool.id] = tool

    if conflicts:
        logger.info(
            f"Resolved {len(conflicts)} ID conflicts (catalog tools won): {', '.join(conflicts[:5])}"
            + (f" and {len(conflicts) - 5} more" if len(conflicts) > 5 else "")
        )

    def _canonicalize_tool(tool: ToolCapability) -> ToolCapability:
        original_id = str(tool.id or "").strip()
        constraints = dict(tool.constraints or {})
        raw_ids: List[str] = []

        if constraints.get("is_alias") and constraints.get("alias_of"):
            raw_ids.append(str(constraints["alias_of"]).strip())
        raw_ids.append(original_id)
        if tool.entrypoint:
            raw_ids.append(str(tool.entrypoint).strip())

        canonical_id = original_id
        for raw_id in raw_ids:
            if not raw_id:
                continue
            runtime_ids = _preferred_runtime_aliases(raw_id)
            if runtime_ids:
                canonical_id = str(runtime_ids[0]).strip() or canonical_id
                break

        if canonical_id == original_id:
            return tool

        alias_ids = [original_id]
        if constraints.get("is_alias") and constraints.get("alias_of"):
            alias_ids.append(str(constraints["alias_of"]).strip())
        alias_ids = _dedupe_preserve_order(alias_ids)
        alias_ids = [alias for alias in alias_ids if alias and alias != canonical_id]

        if alias_ids:
            existing_aliases = constraints.get("alias_ids") or []
            constraints["alias_ids"] = _dedupe_preserve_order(
                [*existing_aliases, *alias_ids]
            )
        constraints.setdefault("catalog_id", original_id)
        tool.id = canonical_id
        tool.constraints = constraints
        return tool

    def _prefer_tool(candidate: ToolCapability, incumbent: ToolCapability) -> bool:
        candidate_constraints = dict(candidate.constraints or {})
        incumbent_constraints = dict(incumbent.constraints or {})
        candidate_is_alias = bool(candidate_constraints.get("is_alias"))
        incumbent_is_alias = bool(incumbent_constraints.get("is_alias"))
        if candidate_is_alias != incumbent_is_alias:
            return not candidate_is_alias

        source_rank = {"catalog": 0, "legacy": 1, "catalog_generated": 2}
        candidate_rank = source_rank.get(str(candidate.source or ""), 99)
        incumbent_rank = source_rank.get(str(incumbent.source or ""), 99)
        return candidate_rank < incumbent_rank

    canonical_tools: Dict[str, ToolCapability] = {}
    for tool in tools_by_id.values():
        canonical = _canonicalize_tool(tool)
        existing = canonical_tools.get(canonical.id)
        if existing is None:
            canonical_tools[canonical.id] = canonical
            continue
        if _prefer_tool(canonical, existing):
            winner, loser = canonical, existing
        else:
            winner, loser = existing, canonical
        winner_constraints = dict(winner.constraints or {})
        loser_constraints = dict(loser.constraints or {})
        winner_constraints["alias_ids"] = _dedupe_preserve_order(
            [
                *(winner_constraints.get("alias_ids") or []),
                *(loser_constraints.get("alias_ids") or []),
                str(loser.id or "").strip(),
                str(loser_constraints.get("catalog_id") or "").strip(),
            ]
        )
        winner.constraints = winner_constraints
        canonical_tools[winner.id] = winner

    return list(canonical_tools.values())


def build_indexes(tools: List[ToolCapability]) -> CapabilityIndex:
    """Build indexes for fast tool lookup.

    Args:
        tools: List of ToolCapability objects

    Returns:
        CapabilityIndex with various lookup maps
    """
    index = CapabilityIndex()

    for tool in tools:
        # By ID
        index.by_id[tool.id] = tool
        constraints = dict(tool.constraints or {})
        for alias in constraints.get("alias_ids") or []:
            alias_id = str(alias or "").strip()
            if alias_id and alias_id != tool.id:
                index.by_alias.setdefault(alias_id, tool.id)
        catalog_id = str(constraints.get("catalog_id") or "").strip()
        if catalog_id and catalog_id != tool.id:
            index.by_alias.setdefault(catalog_id, tool.id)

        # By capability tags
        for cap in tool.capabilities:
            if cap not in index.by_capability:
                index.by_capability[cap] = []
            index.by_capability[cap].append(tool.id)

        # By intent ids
        for intent in getattr(tool, "intents", []) or []:
            if intent not in index.by_intent:
                index.by_intent[intent] = []
            index.by_intent[intent].append(tool.id)

        # By modality
        for mod in tool.modality:
            if mod not in index.by_modality:
                index.by_modality[mod] = []
            index.by_modality[mod].append(tool.id)

        # By package
        if tool.package not in index.by_package:
            index.by_package[tool.package] = []
        index.by_package[tool.package].append(tool.id)

        # By resource type (consumes/produces)
        for resource in tool.consumes + tool.produces:
            if resource not in index.by_resource_type:
                index.by_resource_type[resource] = []
            if tool.id not in index.by_resource_type[resource]:
                index.by_resource_type[resource].append(tool.id)

    return index


def _record_catalog_failure(reason: str) -> None:
    """Best-effort metric/log enrichment for catalog load failures."""
    logger.error(
        "catalog_loader_failed",
        extra={
            "event": "catalog_loader_failed",
            "reason": reason,
        },
    )
    # Optional metrics hook; failure should never block fallback path
    try:
        from brain_researcher.services.agent.monitoring import metrics_collector

        metrics_collector.increment("catalog_load_failures_total")
    except Exception:  # pragma: no cover - defensive metric attempt
        logger.debug("Metrics collector unavailable for catalog failure recording")


# ========================================
# Intents
# ========================================

_INTENT_INDEX: Dict[str, Intent] = {}


@lru_cache()
def load_intents() -> Dict[str, Intent]:
    """Load intent catalog from YAML (cached)."""
    global _INTENT_INDEX
    if _INTENT_INDEX:
        return _INTENT_INDEX

    path = get_repo_root() / "configs" / "catalog" / "intents.yaml"
    if not path.exists():
        _INTENT_INDEX = {}
        return _INTENT_INDEX

    try:
        data = yaml.safe_load(path.read_text()) or []
    except Exception:
        logger.exception("Failed to load intents.yaml")
        _INTENT_INDEX = {}
        return _INTENT_INDEX

    intents: Dict[str, Intent] = {}
    for item in data:
        try:
            intent = Intent(
                id=item["id"],
                name=item.get("name", item["id"]),
                description=item.get("description", ""),
                domains=item.get("domains", []) or [],
                modalities=item.get("modalities", []) or [],
                analysis_level=item.get("analysis_level"),
                inputs=item.get("inputs", []) or [],
                outputs=item.get("outputs", []) or [],
                parents=item.get("parents", []) or [],
                metadata=item.get("metadata", {}) or {},
            )
            intents[intent.id] = intent
        except Exception:
            logger.exception("Failed to parse intent item: %s", item)
            continue

    _INTENT_INDEX = intents
    return _INTENT_INDEX


# ========================================
# Public API
# ========================================


@lru_cache(maxsize=2)
def _get_capability_index(include_local_first: bool = False) -> CapabilityIndex:
    """Get capability index (cached).

    Behavior depends on BR_PLANNER_SOURCE environment variable:
    - 'catalog': Load from capabilities.yaml + enrich + index
    - 'legacy': Return empty index for compatibility-only callers/tests

    Returns:
        CapabilityIndex with tool lookups
    """
    source = get_planner_source()

    if source == "catalog":
        try:
            # Load all configs
            generated_paths = [
                get_repo_root()
                / "configs"
                / "catalog"
                / "capabilities.python.generated.yaml",
                get_repo_root() / "configs" / "catalog" / "capabilities.generated.yaml",
                get_repo_root()
                / "configs"
                / "catalog"
                / "capabilities.niwrap.generated.yaml",
            ]
            capabilities = load_capabilities_yaml(generated_paths=generated_paths)
            legacy_tools = load_tools_catalog_json()
            resources = load_tool_resources()
            containers = load_niwrap_containers()
            mapping = load_niwrap_mapping()
        except Exception:
            logger.exception(
                "Failed to load catalog assets; falling back to legacy mode"
            )
            _record_catalog_failure("load_exception")
            return CapabilityIndex()

        # Merge and enrich
        merged = enrich_and_merge(
            capabilities,
            legacy_tools,
            resources,
            mapping,
            containers,
            include_niwrap=True,
        )
        merged = _filter_local_first_capabilities(
            merged,
            include_local_first=include_local_first,
        )

        # Build and return index
        return build_indexes(merged)
    else:
        # Legacy mode: return empty index
        return CapabilityIndex()


def get_capability_index(include_local_first: bool = False) -> CapabilityIndex:
    return _get_capability_index(include_local_first=include_local_first)


get_capability_index.cache_clear = _get_capability_index.cache_clear  # type: ignore[attr-defined]


@lru_cache()
def load_tool_catalog() -> Dict[str, ToolSpec]:
    """Load the planner catalog from configs/tools_catalog.json (legacy mode).

    This is kept for backward compatibility.

    Returns:
        Dict mapping tool name to ToolSpec
    """
    return load_tools_catalog_json()


def get_tool_spec(name: str) -> Optional[ToolSpec]:
    """Helper to fetch a single tool specification (legacy mode).

    Args:
        name: Tool name

    Returns:
        ToolSpec or None if not found
    """
    return load_tool_catalog().get(name)


def get_tool_by_id(tool_id: str) -> Optional[ToolCapability]:
    """Get tool by ID from capability index.

    Args:
        tool_id: Tool ID (e.g., "fsl.bet.run")

    Returns:
        ToolCapability or None if not found
    """
    index = get_capability_index(include_local_first=True)
    tool = index.by_id.get(tool_id)
    if tool is not None:
        return tool

    canonical_id = index.by_alias.get(tool_id)
    if canonical_id:
        return index.by_id.get(canonical_id)

    for candidate in _preferred_runtime_aliases(tool_id):
        tool = index.by_id.get(candidate)
        if tool is not None:
            return tool
        canonical_id = index.by_alias.get(candidate)
        if canonical_id:
            return index.by_id.get(canonical_id)

    return None


def search_by_capability(
    capability: str,
    *,
    include_local_first: bool = False,
) -> List[ToolCapability]:
    """Search tools by capability tag.

    Args:
        capability: Capability tag (e.g., "skull_strip", "registration")

    Returns:
        List of matching ToolCapability objects
    """
    index = get_capability_index(include_local_first=include_local_first)
    tool_ids = index.by_capability.get(capability, [])
    return [index.by_id[tid] for tid in tool_ids]


def search_by_modality(
    modality: str,
    *,
    include_local_first: bool = False,
) -> List[ToolCapability]:
    """Search tools by modality.

    Args:
        modality: Modality (e.g., "fmri", "smri", "dmri")

    Returns:
        List of matching ToolCapability objects
    """
    index = get_capability_index(include_local_first=include_local_first)
    tool_ids = index.by_modality.get(modality, [])
    return [index.by_id[tid] for tid in tool_ids]


def search_by_package(package: str) -> List[ToolCapability]:
    """Search tools by package.

    Args:
        package: Package name (e.g., "fsl", "ants", "afni")

    Returns:
        List of matching ToolCapability objects
    """
    index = get_capability_index()
    tool_ids = index.by_package.get(package, [])
    return [index.by_id[tid] for tid in tool_ids]


def search_by_intent(
    intent_id: str,
    *,
    include_local_first: bool = False,
) -> List[ToolCapability]:
    """Search tools by declared intent identifier.

    Args:
        intent_id: Intent ID (e.g., "glm_first_level_fmri")

    Returns:
        List of matching ToolCapability objects
    """
    index = get_capability_index(include_local_first=include_local_first)
    tool_ids = index.by_intent.get(intent_id, [])
    return [index.by_id[tid] for tid in tool_ids]


__all__ = [
    # Models
    "ToolSpec",
    "ToolCapability",
    "ResourceSpec",
    "ContainerSpec",
    "ToolMetadata",
    "CapabilityIndex",
    # Loaders
    "load_intents",
    "load_capabilities_yaml",
    "load_tools_catalog_json",
    "load_tool_resources",
    "load_niwrap_containers",
    "load_tool_categories",
    # Enrichment
    "enrich_and_merge",
    "build_indexes",
    # Public API
    "get_capability_index",
    "load_tool_catalog",
    "get_tool_spec",
    "get_tool_by_id",
    "search_by_capability",
    "search_by_modality",
    "search_by_package",
    "search_by_intent",
    # Config
    "get_planner_source",
]
