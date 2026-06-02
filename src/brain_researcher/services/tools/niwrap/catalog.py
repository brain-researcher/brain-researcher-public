"""NiWrap tool catalog and caching.

This module manages loading and caching of NiWrap Boutiques tool definitions.
It provides the main interface for discovering and retrieving tool metadata.

Moved from: archive/mcp_server/tools/niwrap.py
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from brain_researcher.services.tools.niwrap.boutiques import (
    build_tool_definition,
    walk_niwrap_descriptors,
)

logger = logging.getLogger(__name__)


# Global cache for loaded tools
_TOOL_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_INITIALIZED: bool = False


# Initial test subset: representative tools from different packages
_TEST_TOOLS = [
    ("afni", "3dBlurInMask"),
    ("afni", "3dReHo"),
    ("fsl", "bet"),
    ("ants", "antsRegistration"),
]


def _versioned_candidate_name(tool_name: str) -> str | None:
    normalized = str(tool_name or "").strip()
    if not normalized or not normalized.endswith(".run"):
        return None
    short_name = normalized[: -len(".run")]
    parts = short_name.split(".")
    if len(parts) < 2:
        return None

    package = parts[0]
    app = parts[-1]
    prefix = f"{package}."
    suffix = f".{app}.run"
    matches = sorted(
        name
        for name in _TOOL_CACHE
        if name.startswith(prefix) and name.endswith(suffix)
    )
    if not matches:
        return None
    return matches[-1]


def _candidate_tool_names(tool_name: str) -> list[str]:
    normalized = str(tool_name or "").strip()
    if not normalized:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str | None) -> None:
        candidate_name = str(candidate or "").strip()
        if not candidate_name or candidate_name in seen:
            return
        candidates.append(candidate_name)
        seen.add(candidate_name)

    _add(normalized)

    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_catalog_tool_ids,
        )

        for candidate in resolve_catalog_tool_ids(normalized, include_self=False):
            _add(candidate)
    except Exception:
        pass

    return candidates


def _initialize_cache(
    packages: List[str] | None = None,
    limit: int | None = None,
    test_mode: bool = False,
) -> None:
    """Initialize the tool cache by loading all available tools.

    Args:
        packages: Optional list of packages to load
        limit: Optional limit on number of tools
        test_mode: If True, only load test tools
    """
    global _TOOL_CACHE, _CACHE_INITIALIZED

    if _CACHE_INITIALIZED:
        return

    logger.info("Initializing NiWrap tool cache...")

    if test_mode:
        # Load only test tools
        test_packages = {pkg for pkg, _ in _TEST_TOOLS}
        descriptors = walk_niwrap_descriptors(
            packages=list(test_packages) if packages is None else packages,
            limit=2000,
        )

        test_tool_set = set(_TEST_TOOLS)
        found_tools = set()

        for descriptor in descriptors:
            tool_key = (descriptor.package, descriptor.app)
            if tool_key in test_tool_set and tool_key not in found_tools:
                try:
                    tool_def = build_tool_definition(descriptor)
                    # Add internal metadata
                    tool_def["input_schema"]["properties"]["_tool_name"] = {
                        "type": "string",
                        "default": tool_def["name"],
                        "description": "Internal: tool name for execution",
                    }
                    tool_def["input_schema"]["properties"]["_preview"] = {
                        "type": "boolean",
                        "default": False,
                        "description": "Internal: if true, only return command without executing",
                    }
                    tool_def["input_schema"]["additionalProperties"] = True
                    _TOOL_CACHE[tool_def["name"]] = tool_def
                    found_tools.add(tool_key)
                except Exception as exc:
                    logger.warning(
                        f"Failed to build tool definition for {descriptor.package}.{descriptor.app}: {exc}"
                    )

            if len(found_tools) >= len(test_tool_set):
                break
    else:
        # Load all tools (or filtered)
        descriptors = walk_niwrap_descriptors(packages=packages, limit=limit)

        for descriptor in descriptors:
            try:
                tool_def = build_tool_definition(descriptor)
                # Add internal metadata
                tool_def["input_schema"]["properties"]["_tool_name"] = {
                    "type": "string",
                    "default": tool_def["name"],
                    "description": "Internal: tool name for execution",
                }
                tool_def["input_schema"]["properties"]["_preview"] = {
                    "type": "boolean",
                    "default": False,
                    "description": "Internal: if true, only return command without executing",
                }
                tool_def["input_schema"]["additionalProperties"] = True
                _TOOL_CACHE[tool_def["name"]] = tool_def
            except Exception as exc:
                logger.warning(
                    f"Failed to build tool definition for {descriptor.package}.{descriptor.app}: {exc}"
                )

    _CACHE_INITIALIZED = True
    logger.info(f"Cached {len(_TOOL_CACHE)} NiWrap tools")


def clear_cache() -> None:
    """Clear the tool cache and force re-initialization on next access."""
    global _TOOL_CACHE, _CACHE_INITIALIZED
    _TOOL_CACHE.clear()
    _CACHE_INITIALIZED = False
    logger.info("NiWrap tool cache cleared")


def get_tool_by_name(tool_name: str) -> Optional[Dict[str, Any]]:
    """Get a specific tool by name from the cache.

    Args:
        tool_name: Full NiWrap tool name or runtime canonical alias
            (e.g., "afni.24.2.06.3dBlurInMask.run" or "fsl_bet")

    Returns:
        Tool definition dict or None if not found
    """
    if not _CACHE_INITIALIZED:
        _initialize_cache(test_mode=False)

    for candidate in _candidate_tool_names(tool_name):
        direct = _TOOL_CACHE.get(candidate)
        if direct is not None:
            return direct
        versioned = _versioned_candidate_name(candidate)
        if versioned is not None:
            return _TOOL_CACHE.get(versioned)
    return None


def get_niwrap_tools(
    packages: List[str] | None = None,
    limit: int | None = None,
    test_mode: bool = False,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """Get NiWrap tool definitions.

    Uses caching by default for efficient repeated access. The cache is
    initialized on first call and reused for subsequent calls.

    Args:
        packages: Optional list of packages to load (e.g., ["afni", "fsl"])
        limit: Optional limit on number of tools to load
        test_mode: If True, only load a small test subset
        use_cache: If True (default), use cached tools when available

    Returns:
        List of tool definitions

    Example:
        >>> # Load all tools with caching
        >>> tools = get_niwrap_tools()
        >>> len(tools)
        ~1900

        >>> # Load only test tools
        >>> test_tools = get_niwrap_tools(test_mode=True)
        >>> len(test_tools)
        4

        >>> # Load specific packages
        >>> afni_tools = get_niwrap_tools(packages=["afni"])
    """
    # Initialize cache if needed
    if use_cache and not _CACHE_INITIALIZED:
        _initialize_cache(packages=packages, limit=limit, test_mode=test_mode)

    # If using cache and it's initialized, return filtered results from cache
    if use_cache and _CACHE_INITIALIZED:
        tools = list(_TOOL_CACHE.values())

        # Apply filters if needed
        if packages:
            tools = [
                t
                for t in tools
                if any(t["name"].startswith(f"{pkg}.") for pkg in packages)
            ]

        if limit:
            tools = tools[:limit]

        return tools

    # No caching - load tools directly
    tools: List[Dict[str, Any]] = []

    if test_mode:
        test_packages = {pkg for pkg, _ in _TEST_TOOLS}
        descriptors = walk_niwrap_descriptors(
            packages=list(test_packages) if packages is None else packages,
            limit=2000,
        )

        test_tool_set = set(_TEST_TOOLS)
        found_tools = set()

        for descriptor in descriptors:
            tool_key = (descriptor.package, descriptor.app)
            if tool_key in test_tool_set and tool_key not in found_tools:
                try:
                    tool_def = build_tool_definition(descriptor)
                    tool_def["input_schema"]["properties"]["_tool_name"] = {
                        "type": "string",
                        "default": tool_def["name"],
                        "description": "Internal: tool name for execution",
                    }
                    tool_def["input_schema"]["properties"]["_preview"] = {
                        "type": "boolean",
                        "default": False,
                        "description": "Internal: if true, only return command without executing",
                    }
                    tool_def["input_schema"]["additionalProperties"] = True
                    tools.append(tool_def)
                    found_tools.add(tool_key)
                    logger.info(f"Loaded NiWrap tool: {tool_def['name']}")
                except Exception as exc:
                    logger.warning(
                        f"Failed to build tool definition for {descriptor.package}.{descriptor.app}: {exc}"
                    )

            if len(found_tools) >= len(test_tool_set):
                break
    else:
        descriptors = walk_niwrap_descriptors(packages=packages, limit=limit)

        for descriptor in descriptors:
            try:
                tool_def = build_tool_definition(descriptor)
                tool_def["input_schema"]["properties"]["_tool_name"] = {
                    "type": "string",
                    "default": tool_def["name"],
                    "description": "Internal: tool name for execution",
                }
                tool_def["input_schema"]["properties"]["_preview"] = {
                    "type": "boolean",
                    "default": False,
                    "description": "Internal: if true, only return command without executing",
                }
                tool_def["input_schema"]["additionalProperties"] = True
                tools.append(tool_def)
                logger.debug(f"Loaded NiWrap tool: {tool_def['name']}")
            except Exception as exc:
                logger.warning(
                    f"Failed to build tool definition for {descriptor.package}.{descriptor.app}: {exc}"
                )

    logger.info(f"Loaded {len(tools)} NiWrap tools")
    return tools


def search_tools(
    query: str,
    package: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search for tools matching a query.

    Args:
        query: Search query (searches name, description, tags)
        package: Optional package filter
        limit: Maximum number of results

    Returns:
        List of matching tool definitions
    """
    if not _CACHE_INITIALIZED:
        _initialize_cache(test_mode=False)

    query_lower = query.lower()
    matches = []

    for tool_def in _TOOL_CACHE.values():
        # Filter by package if specified
        if package and not tool_def["name"].startswith(f"{package}."):
            continue

        # Search in name, description, and tags
        name = tool_def.get("name", "").lower()
        description = tool_def.get("description", "").lower()
        tags = [t.lower() for t in tool_def.get("tags", [])]

        if (
            query_lower in name
            or query_lower in description
            or any(query_lower in tag for tag in tags)
        ):
            matches.append(tool_def)

            if len(matches) >= limit:
                break

    return matches


__all__ = [
    "get_niwrap_tools",
    "get_tool_by_name",
    "clear_cache",
    "search_tools",
]
