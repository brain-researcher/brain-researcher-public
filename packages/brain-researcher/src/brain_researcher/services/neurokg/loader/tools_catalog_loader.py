"""Ingest tools from the catalog into BR-KG.

This loader is intentionally lightweight and idempotent. It parses the
capabilities YAML and maps each tool into Tool/ToolVersion nodes plus
relationships for resources (consumes/produces), modalities, and
capability families. Optional evidence data (publications, validated
collections) can also be attached.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from brain_researcher.config.paths import get_config_root
from brain_researcher.services.shared.planner.models import ResourceType
from brain_researcher.services.tools.catalog_loader import (
    CATEGORY_TO_KIND,
    load_categories,
    load_exposed_tools,
    load_niwrap_mapping,
    load_tools_catalog,
    resolve_category,
    resolve_niwrap_metadata,
)


def _resolve_configs_dir() -> Path:
    """Resolve repo-level configs directory relative to this module."""
    path = Path(__file__).resolve()
    for parent in path.parents:
        candidate = parent / "configs"
        if candidate.exists():
            return candidate
    return get_config_root()


CONFIGS_DIR = _resolve_configs_dir()


@lru_cache(maxsize=1)
def load_intent_config() -> dict[str, Any]:
    """Load intent priority/filters for primary_intent selection."""
    # New preferred name (kept separate from tool catalog artifacts).
    # Backward compatible fallback: tool_intents.yaml
    candidates = [CONFIGS_DIR / "intent_priority.yaml", CONFIGS_DIR / "tool_intents.yaml"]
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
        data["aliases"] = {str(k).lower(): v for k, v in aliases.items() if k is not None}

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


def parse_tool_id(tool_id: str, package: Optional[str] = None) -> dict[str, Optional[str]]:
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


def normalize_op_key(op: Optional[str]) -> Optional[str]:
    if not op:
        return None
    return re.sub(r"[^a-z0-9]+", "", op.lower())


def resolve_op_key_method(op_key: Optional[str], intent_config: dict[str, Any]) -> Optional[str]:
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
        for prefix, method in sorted(op_key_prefix_aliases.items(), key=lambda kv: -len(kv[0])):
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


def _version_tuple(version: Optional[str]) -> Optional[tuple[int, ...]]:
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
    pinned_version: Optional[str],
) -> Optional[str]:
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
        default_tid = _pick_default_tool_id(tool_ids, meta_map, pinned_tool_ids, pinned_version)
        if default_tid:
            default_by_group[group_id] = default_tid
    return default_by_group


def _policy_allows(value: Optional[str], allow: set[str], deny: set[str]) -> bool:
    if value in deny:
        return False
    if allow and value not in allow:
        return False
    return True

def select_primary_intent(
    intents: list[str],
    category: Optional[str],
    families: list[str],
    intent_config: dict[str, Any],
) -> Optional[str]:
    """Pick a primary intent, excluding implementation-only intents."""
    default_impl_intents = {
        "generic_container_op",
        "python_op",
        "mcp_tool",
        "wrapper_tool",
        "service_tool",
    }
    impl_intents = set(intent_config.get("impl_intents", []) or default_impl_intents)
    priority = intent_config.get("priority", []) or intent_config.get("method_priority", []) or []

    # Canonicalize intents/category/families via config aliases (stable cross-software method ids).
    aliases = intent_config.get("aliases", {}) or {}
    def _alias(value: Optional[str]) -> Optional[str]:
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
) -> Iterable[tuple[dict[str, Any], dict[str, Any], list[tuple[str, str, str]], list[str], list[str]]]:
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
            priority = intent_config.get("priority") or intent_config.get("method_priority") or []
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
                normalize_op_key(v) for v in (exposure_policy.get("allow_op_keys", []) or [])
            )
            if k
        }
        deny_ops = {
            k
            for k in (
                normalize_op_key(v) for v in (exposure_policy.get("deny_op_keys", []) or [])
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
        catalog_entry: Optional[dict[str, Any]] = None
        if catalog is not None:
            catalog_entry = catalog.get(tool_id)

        intents: list[str] = []
        intents_from_niwrap = False
        category: Optional[str] = None
        kind: Optional[str] = None
        display_name: Optional[str] = None
        source: Optional[str] = None
        confidence: Optional[float] = None
        runtime: Optional[str] = None
        mcp_tool: Optional[bool] = None

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
            package = tool.get("package") or (catalog_entry or {}).get("package") or tool_id.split(".")[0]
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
        is_default = bool(group_id and default_by_group and default_by_group.get(group_id) == tool_id)

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
        impl_intents = set(intent_config.get("impl_intents", []) or default_impl_intents)
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
            elif intents_from_niwrap and len(method_intents) == 1 and method_intents[0] != mapped_method:
                # NiWrap-derived intents are a good default, but for some ops the op_key is more reliable
                # (e.g. FEATquery is extraction, not "fit a GLM"). Allow op_key_aliases to override
                # a single inferred method intent, while keeping implementation intents.
                canonical_intents = [i for i in canonical_intents if i in impl_intents]
                canonical_intents.append(mapped_method)

        intents = canonical_intents
        primary_intent = select_primary_intent(intents, category, list(families), intent_config)

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
            exposed = exposed and _policy_allows(primary_intent, allow_primary, deny_primary)
            exposed = exposed and _policy_allows(software.lower() if software else software, allow_soft, deny_soft)
            exposed = exposed and _policy_allows(runtime_kind.lower(), allow_runtime, deny_runtime)
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
        tx.merge_rel("Tool", "tool_id", tool_id, "DOCUMENTED_IN", "Publication", "doi", doi)

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


def ingest(tx: Any, caps_path: Path | str, evidence: dict[str, Any] | None = None) -> None:
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
        tx.merge_rel("Tool", "tool_id", tool_id, "HAS_VERSION", "ToolVersion", "version_id", version_id)

        for _, res, rel in resource_edges:
            # Use ResourceType nodes to stay consistent with KG resource ontology
            tx.merge_node("ResourceType", "name", {"name": res})
            tx.merge_rel("ToolVersion", "version_id", version_id, rel, "ResourceType", "name", res)

        for mod in modalities:
            tx.merge_node("Modality", "name", {"name": mod})
            tx.merge_rel("Tool", "tool_id", tool_id, "SUPPORTS_MODALITY", "Modality", "name", mod)

        for fam in families:
            tx.merge_node("TaskFamily", "name", {"name": fam})
            tx.merge_rel("Tool", "tool_id", tool_id, "IMPLEMENTS_FAMILY", "TaskFamily", "name", fam)

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
        raise ValueError("run_id, tool_id, and version_id are required for tool run ingestion")

    tx.merge_node("Tool", "tool_id", {"tool_id": tool_id})
    tx.merge_node("ToolVersion", "version_id", {"version_id": version_id})
    tx.merge_rel("Tool", "tool_id", tool_id, "HAS_VERSION", "ToolVersion", "version_id", version_id)

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
            or (yaml.safe_dump(provenance.get("parameters")) if provenance.get("parameters") else None),
            "runtime_kind": provenance.get("runtime_kind"),
        },
    )
    tx.merge_rel("ToolRun", "run_id", run_id, "EXECUTED_VERSION", "ToolVersion", "version_id", version_id)

    for ds in provenance.get("inputs", []) or []:
        ds_id = ds.get("id") if isinstance(ds, dict) else ds
        if not ds_id:
            continue
        tx.merge_node("DataResource", "id", {"id": ds_id, "resource_id": ds_id})
        tx.merge_rel("ToolRun", "run_id", run_id, "USED_RESOURCE", "DataResource", "id", ds_id)

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
