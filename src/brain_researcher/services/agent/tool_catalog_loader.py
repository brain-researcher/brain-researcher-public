"""
Tool catalog loader for building the searchable tool index.

This module loads tool metadata from:
- configs/catalog/tool_mappings.yaml: Tool aliases and examples
- niwrap_containers.yaml: Container images and runtime config
- NiWrap catalog (future): Additional tool metadata

The loader produces ToolEntry objects that can be indexed for search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from brain_researcher.config.paths import get_repo_root, resolve_from_config

from .tool_index import ToolEntry

# Global cache for the tool index
_TOOL_INDEX_CACHE: Optional["ToolIndex"] = None


def _load_yaml(path: Path) -> Dict:
    """Load a YAML file and return its contents."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _get_config_path(filename: str) -> Path:
    """
    Resolve path to a config file, checking multiple locations.

    Priority order:
    1. configs/ in repo root
    2. brain_researcher/services/agent/ (for service-local configs)
    """
    candidates = [
        get_repo_root() / "configs" / filename,
        Path(__file__).parent / filename,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Return first candidate even if it doesn't exist
    # (caller will handle missing file)
    return candidates[0]


def _get_catalog_config_path(filename: str) -> Path:
    """Resolve a config file under ``configs/catalog``."""

    return resolve_from_config("catalog", filename)


def load_tool_mappings() -> Dict:
    """
    Load tool_mappings.yaml from config directory.

    Returns:
        Dictionary with tool categories and their metadata
    """
    path = _get_catalog_config_path("tool_mappings.yaml")
    return _load_yaml(path)


def load_niwrap_containers() -> Dict:
    """
    Load niwrap_containers.yaml from config directory.

    Returns:
        Dictionary mapping tool names to container configs
    """
    path = _get_config_path("niwrap_containers.yaml")
    return _load_yaml(path)


def load_tool_synonyms() -> Dict[str, List[str]]:
    """
    Load tool_synonyms.yaml from configs/catalog/.

    Returns:
        Dictionary mapping terms to their synonyms
    """
    path = _get_catalog_config_path("tool_synonyms.yaml")
    data = _load_yaml(path)

    # Flatten the structure if needed
    synonyms = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                synonyms[key.lower()] = [s.lower() for s in value]
            elif isinstance(value, dict) and "synonyms" in value:
                synonyms[key.lower()] = [s.lower() for s in value["synonyms"]]

    return synonyms


def _extract_description(tool_data: Dict) -> str:
    """
    Extract a description from tool metadata.

    Priority:
    1. description field
    2. First example query
    3. Aliases joined
    4. Empty string
    """
    if "description" in tool_data:
        return tool_data["description"]

    if "example_queries" in tool_data and tool_data["example_queries"]:
        return tool_data["example_queries"][0]

    if "aliases" in tool_data and tool_data["aliases"]:
        return f"Tool for {', '.join(tool_data['aliases'][:3])}"

    return ""


def build_tool_catalog() -> List[ToolEntry]:
    """
    Build a comprehensive tool catalog from all available sources.

    Returns:
        List of ToolEntry objects for indexing
    """
    entries: List[ToolEntry] = []

    # Load source data
    tool_mappings = load_tool_mappings()
    niwrap_containers = load_niwrap_containers()

    # Process tool_mappings.yaml
    for category, tools in tool_mappings.items():
        if not isinstance(tools, dict):
            continue

        for tool_name, tool_data in tools.items():
            if not isinstance(tool_data, dict):
                continue

            # Build tool ID (category.tool_name)
            tool_id = f"{category}.{tool_name}"

            # Extract metadata
            aliases = tool_data.get("aliases", [])
            description = _extract_description(tool_data)
            tags = tool_data.get("tags", [])

            # Try to find container image
            image = None
            container_key = tool_name
            if container_key in niwrap_containers:
                container_info = niwrap_containers[container_key]
                if isinstance(container_info, dict):
                    image = container_info.get("image")

            # Create entry
            entry = ToolEntry(
                id=tool_id,
                name=tool_name,
                description=description,
                tags=tags,
                image=image,
                aliases=aliases,
                category=category,
            )
            entries.append(entry)

    # Add NiWrap containers that aren't in tool_mappings
    processed_names = {entry.name for entry in entries}
    for container_name, container_data in niwrap_containers.items():
        if container_name in processed_names:
            continue
        if not isinstance(container_data, dict):
            continue

        # Create entry for this container
        entry = ToolEntry(
            id=f"niwrap.{container_name}",
            name=container_name,
            description=f"Neuroimaging tool: {container_name}",
            tags=["niwrap", "neuroimaging"],
            image=container_data.get("image"),
            aliases=[],
            category="niwrap",
        )
        entries.append(entry)

    return entries


def get_tool_index() -> "ToolIndex":
    """
    Get or create the cached tool index.

    This function is the main entry point for accessing the tool search
    functionality. It builds the index on first call and caches it.

    Returns:
        Initialized ToolIndex instance
    """
    global _TOOL_INDEX_CACHE

    if _TOOL_INDEX_CACHE is None:
        # Import here to avoid circular dependency
        from .tool_index import ToolIndex

        # Build catalog and index
        entries = build_tool_catalog()
        synonyms = load_tool_synonyms()

        _TOOL_INDEX_CACHE = ToolIndex(entries, synonyms)

    return _TOOL_INDEX_CACHE


def clear_tool_index_cache():
    """
    Clear the cached tool index.

    Useful for testing or when tool metadata has been updated.
    """
    global _TOOL_INDEX_CACHE
    _TOOL_INDEX_CACHE = None
    try:
        from brain_researcher.services.agent.resolution_memory import (
            invalidate_capability_knowledge,
        )

        invalidate_capability_knowledge()
    except Exception:
        # Best effort only; cache invalidation should not fail catalog refresh.
        pass


__all__ = [
    "build_tool_catalog",
    "get_tool_index",
    "clear_tool_index_cache",
    "load_tool_mappings",
    "load_niwrap_containers",
    "load_tool_synonyms",
]
