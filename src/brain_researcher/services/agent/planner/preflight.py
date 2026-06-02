"""Lightweight preflight checks for planner tool candidates.

This module provides a simplified preflight check interface optimized for the
planner's tool selection workflow. It wraps the more comprehensive preflight
system from services/agent/preflight.py.

The checks performed are:
- Container tools: Image existence, CVMFS availability
- Python tools: Module importability

Results are structured for easy scoring and candidate ranking.

PR-3 Enhancement: Adds Redis-backed caching with TTL to avoid repeated checks.
"""

from __future__ import annotations

import importlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain_researcher.services.agent.planner.cache import (
    clear_preflight_cache as _clear_cache,
)
from brain_researcher.services.agent.planner.cache import (
    compute_cache_key,
    compute_tool_digest,
    get_preflight_cache,
)
from brain_researcher.services.agent.planner.catalog_loader import ToolCapability
from brain_researcher.services.agent.planner.config_loader import load_planner_config

logger = logging.getLogger(__name__)


_PREFLIGHT_CONFIG: Optional[Dict[str, Any]] = None


def get_preflight_config() -> Dict[str, Any]:
    """Load and cache planner preflight configuration."""
    global _PREFLIGHT_CONFIG
    if _PREFLIGHT_CONFIG is None:
        _PREFLIGHT_CONFIG = load_planner_config("preflight.yaml") or {}
    return _PREFLIGHT_CONFIG


class PreflightStatus(str, Enum):
    """Structured status codes for preflight checks.

    These replace string matching in resource_fit scoring for better reliability.
    """

    # Container statuses
    CVMFS_AVAILABLE = "cvmfs_available"
    LOCAL_AVAILABLE = "local_available"
    NOT_AVAILABLE = "not_available"

    # Python statuses
    IMPORT_SUCCESS = "import_success"
    IMPORT_FAILED = "import_failed"

    # Common statuses
    NOT_REQUIRED = "not_required"
    CHECK_ERROR = "check_error"


@dataclass
class PreflightCheck:
    """Result of a single preflight check.

    Attributes:
        name: Check identifier (e.g., "container_image", "python_import")
        passed: Whether the check passed
        detail: Optional human-readable detail message (especially for failures)
        status_code: Structured status code for programmatic checking
    """

    name: str
    passed: bool
    detail: Optional[str] = None
    status_code: Optional[PreflightStatus] = None


@dataclass
class PreflightReport:
    """Aggregated preflight results for a tool.

    Attributes:
        tool_id: Tool capability ID
        passed: Overall pass/fail (AND of all check results)
        checks: Dict of check name → PreflightCheck
        runtime_kind: Runtime kind (container, python, mcp)
        python_module: Python module path (if runtime_kind is python)
        python_function: Python function name (if runtime_kind is python)
    """

    tool_id: str
    passed: bool
    checks: Dict[str, PreflightCheck] = field(default_factory=dict)
    runtime_kind: Optional[str] = None
    python_module: Optional[str] = None
    python_function: Optional[str] = None


def _check_container_image(tool: ToolCapability) -> PreflightCheck:
    """Check if container image is accessible.

    Args:
        tool: Tool capability to check

    Returns:
        PreflightCheck indicating whether image is accessible
    """
    container_cfg = get_preflight_config().get("checks", {}).get("container", {})

    if not container_cfg.get("enabled", True):
        return PreflightCheck(
            "container_image", True, "disabled", PreflightStatus.NOT_REQUIRED
        )

    if tool.runtime_kind != "container":
        return PreflightCheck(
            "container_image", True, "not-required", PreflightStatus.NOT_REQUIRED
        )

    if not tool.container:
        return PreflightCheck(
            "container_image", False, "no container spec", PreflightStatus.NOT_AVAILABLE
        )

    image = tool.container.image
    if not image:
        return PreflightCheck(
            "container_image",
            False,
            "no image configured",
            PreflightStatus.NOT_AVAILABLE,
        )

    # Check if image path exists
    # For CVMFS paths, just check if CVMFS is mounted
    if "/cvmfs/" in image:
        cvmfs_root = Path("/cvmfs")
        if not cvmfs_root.exists():
            return PreflightCheck(
                "container_image",
                False,
                "CVMFS not mounted",
                PreflightStatus.NOT_AVAILABLE,
            )
        # CVMFS is mounted - assume image is accessible
        # (full validation would be expensive)
        return PreflightCheck(
            "container_image", True, "CVMFS accessible", PreflightStatus.CVMFS_AVAILABLE
        )

    # For local paths, check existence
    image_path = Path(image)
    if not image_path.exists():
        return PreflightCheck(
            "container_image",
            False,
            f"image not found: {image}",
            PreflightStatus.NOT_AVAILABLE,
        )

    return PreflightCheck(
        "container_image",
        True,
        "local image available",
        PreflightStatus.LOCAL_AVAILABLE,
    )


def _check_python_import(tool: ToolCapability) -> PreflightCheck:
    """Check if Python module is importable.

    Args:
        tool: Tool capability to check

    Returns:
        PreflightCheck indicating whether module can be imported
    """
    python_cfg = get_preflight_config().get("checks", {}).get("python", {})

    if not python_cfg.get("enabled", True):
        return PreflightCheck(
            "python_import", True, "disabled", PreflightStatus.NOT_REQUIRED
        )

    if tool.runtime_kind != "python":
        return PreflightCheck(
            "python_import", True, "not-required", PreflightStatus.NOT_REQUIRED
        )

    if not tool.python:
        return PreflightCheck(
            "python_import", False, "no python spec", PreflightStatus.IMPORT_FAILED
        )

    module_name = getattr(tool.python, "module", None)
    func_name = getattr(tool.python, "function", None)

    if not module_name:
        return PreflightCheck(
            "python_import", False, "no python module", PreflightStatus.NOT_AVAILABLE
        )

    try:
        module = importlib.import_module(module_name)
        if func_name:
            if not hasattr(module, func_name):
                return PreflightCheck(
                    "python_import",
                    False,
                    f"function '{func_name}' not found in {module_name}",
                    PreflightStatus.IMPORT_FAILED,
                )
        return PreflightCheck(
            "python_import",
            True,
            "module imported successfully",
            PreflightStatus.IMPORT_SUCCESS,
        )
    except ImportError as exc:
        return PreflightCheck(
            "python_import",
            False,
            f"import failed: {exc}",
            PreflightStatus.IMPORT_FAILED,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return PreflightCheck(
            "python_import",
            False,
            f"unexpected error: {exc}",
            PreflightStatus.CHECK_ERROR,
        )


def run_preflight(tool: ToolCapability, use_cache: bool = True) -> PreflightReport:
    """Execute preflight checks for the given tool.

    Performs lightweight checks appropriate for tool selection:
    - Container tools: image accessibility
    - Python tools: module importability

    PR-3: Now supports caching with Redis/in-memory TTL to avoid repeated checks.

    Args:
        tool: Tool capability to check
        use_cache: Whether to use cache (default True)

    Returns:
        PreflightReport with overall status and individual check results

    Examples:
        >>> from brain_researcher.services.agent.planner.catalog_loader import get_tool_by_id
        >>> tool = get_tool_by_id("fsl_bet")
        >>> report = run_preflight(tool)
        >>> if report.passed:
        ...     print(f"{tool.name} is ready to use")
    """
    # Check cache first
    if use_cache:
        cache = get_preflight_cache()
        digest = compute_tool_digest(tool)
        cache_key = compute_cache_key(tool.id, digest)

        cached = cache.get(cache_key)
        if cached:
            # Reconstruct report from cached data
            report = PreflightReport(
                tool_id=cached["tool_id"],
                passed=cached["passed"],
                runtime_kind=cached.get("runtime_kind"),
                python_module=cached.get("python_module"),
                python_function=cached.get("python_function"),
            )
            for check_name, check_data in cached.get("checks", {}).items():
                status_code = check_data.get("status_code")
                if status_code:
                    status_code = PreflightStatus(status_code)
                report.checks[check_name] = PreflightCheck(
                    name=check_data["name"],
                    passed=check_data["passed"],
                    detail=check_data.get("detail"),
                    status_code=status_code,
                )
            logger.debug(f"Preflight cache hit for {tool.id}")
            return report

    # Run checks
    report = PreflightReport(
        tool_id=tool.id,
        passed=True,
        runtime_kind=tool.runtime_kind,
        python_module=getattr(tool.python, "module", None) if tool.python else None,
        python_function=getattr(tool.python, "function", None) if tool.python else None,
    )

    checks = [
        _check_container_image(tool),
        _check_python_import(tool),
    ]

    for check in checks:
        report.checks[check.name] = check
        # Overall report fails if any check fails
        report.passed = report.passed and check.passed

    # Store in cache
    if use_cache:
        cache = get_preflight_cache()
        digest = compute_tool_digest(tool)
        cache_key = compute_cache_key(tool.id, digest)

        # Serialize report for caching
        cache_data = {
            "tool_id": report.tool_id,
            "passed": report.passed,
            "runtime_kind": report.runtime_kind,
            "python_module": report.python_module,
            "python_function": report.python_function,
            "checks": {
                name: {
                    "name": check.name,
                    "passed": check.passed,
                    "detail": check.detail,
                    "status_code": (
                        check.status_code.value if check.status_code else None
                    ),
                }
                for name, check in report.checks.items()
            },
        }
        cache.set(cache_key, cache_data)
        logger.debug(f"Preflight cache miss for {tool.id}, stored result")

    return report


def preflight_batch(
    tools: list[ToolCapability],
    use_cache: bool = True,
    concurrent: Optional[bool] = None,
    max_workers: Optional[int] = None,
) -> Dict[str, PreflightReport]:
    """Run preflight checks on multiple tools with caching and concurrency.

    PR-3: Enhanced with:
    - Deduplication of identical tools
    - Batch cache lookup (Redis pipeline)
    - Concurrent execution for uncached checks
    - Batch cache storage

    Args:
        tools: List of tool capabilities to check
        use_cache: Whether to use cache (default True)
        concurrent: Whether to run checks concurrently (default True)
        max_workers: Max concurrent workers (default 4)

    Returns:
        Dict mapping tool IDs to preflight reports

    Examples:
        >>> from brain_researcher.services.agent.planner.catalog_loader import search_by_capability
        >>> tools = search_by_capability("skull_strip")
        >>> reports = preflight_batch(tools)
        >>> passing = [t for t, r in reports.items() if r.passed]
    """
    if not tools:
        return {}

    batch_cfg = get_preflight_config().get("batch", {})
    if concurrent is None:
        concurrent = batch_cfg.get("concurrent", True)
    if max_workers is None:
        max_workers = batch_cfg.get("max_workers", 4)

    # Deduplicate tools by ID
    unique_tools = {tool.id: tool for tool in tools}
    tools_list = list(unique_tools.values())

    # Try batch cache lookup first
    results: Dict[str, PreflightReport] = {}
    uncached_tools: List[ToolCapability] = []

    if use_cache:
        cache = get_preflight_cache()

        # Build cache keys
        cache_keys = []
        tool_by_cache_key = {}
        for tool in tools_list:
            digest = compute_tool_digest(tool)
            cache_key = compute_cache_key(tool.id, digest)
            cache_keys.append(cache_key)
            tool_by_cache_key[cache_key] = tool

        # Batch get from cache
        cached_data = cache.get_many(cache_keys)

        for cache_key, data in cached_data.items():
            tool = tool_by_cache_key[cache_key]
            if data:
                # Cache hit - reconstruct report
                report = PreflightReport(
                    tool_id=data["tool_id"],
                    passed=data["passed"],
                    runtime_kind=data.get("runtime_kind"),
                    python_module=data.get("python_module"),
                    python_function=data.get("python_function"),
                )
                for check_name, check_data in data.get("checks", {}).items():
                    status_code = check_data.get("status_code")
                    if status_code:
                        status_code = PreflightStatus(status_code)
                    report.checks[check_name] = PreflightCheck(
                        name=check_data["name"],
                        passed=check_data["passed"],
                        detail=check_data.get("detail"),
                        status_code=status_code,
                    )
                results[tool.id] = report
                logger.debug(f"Preflight batch cache hit for {tool.id}")
            else:
                # Cache miss
                uncached_tools.append(tool)
    else:
        uncached_tools = tools_list

    # Run checks for uncached tools
    if uncached_tools:
        if concurrent and len(uncached_tools) > 1:
            # Concurrent execution
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_tool = {
                    executor.submit(_run_preflight_no_cache, tool): tool
                    for tool in uncached_tools
                }

                for future in as_completed(future_to_tool):
                    tool = future_to_tool[future]
                    try:
                        report = future.result()
                        results[tool.id] = report
                    except Exception as exc:
                        logger.error(f"Preflight check failed for {tool.id}: {exc}")
                        # Create failed report
                        results[tool.id] = PreflightReport(
                            tool_id=tool.id,
                            passed=False,
                            checks={
                                "error": PreflightCheck(
                                    "error", False, f"Exception: {exc}"
                                )
                            },
                        )
        else:
            # Sequential execution
            for tool in uncached_tools:
                try:
                    report = _run_preflight_no_cache(tool)
                    results[tool.id] = report
                except Exception as exc:
                    logger.error(f"Preflight check failed for {tool.id}: {exc}")
                    results[tool.id] = PreflightReport(
                        tool_id=tool.id,
                        passed=False,
                        checks={
                            "error": PreflightCheck("error", False, f"Exception: {exc}")
                        },
                    )

        # Batch store uncached results
        if use_cache and results:
            cache = get_preflight_cache()
            cache_items = {}

            for tool_id, report in results.items():
                if tool_id in [t.id for t in uncached_tools]:
                    tool = unique_tools[tool_id]
                    digest = compute_tool_digest(tool)
                    cache_key = compute_cache_key(tool.id, digest)

                    cache_data = {
                        "tool_id": report.tool_id,
                        "passed": report.passed,
                        "runtime_kind": report.runtime_kind,
                        "python_module": report.python_module,
                        "python_function": report.python_function,
                        "checks": {
                            name: {
                                "name": check.name,
                                "passed": check.passed,
                                "detail": check.detail,
                                "status_code": (
                                    check.status_code.value
                                    if check.status_code
                                    else None
                                ),
                            }
                            for name, check in report.checks.items()
                        },
                    }
                    cache_items[cache_key] = cache_data

            if cache_items:
                cache.set_many(cache_items)
                logger.debug(f"Stored {len(cache_items)} preflight results in cache")

    return results


def _run_preflight_no_cache(tool: ToolCapability) -> PreflightReport:
    """Run preflight without cache (internal helper for batch operations)."""
    report = PreflightReport(
        tool_id=tool.id,
        passed=True,
        runtime_kind=tool.runtime_kind,
        python_module=getattr(tool.python, "module", None) if tool.python else None,
        python_function=getattr(tool.python, "function", None) if tool.python else None,
    )

    checks = [
        _check_container_image(tool),
        _check_python_import(tool),
    ]

    for check in checks:
        report.checks[check.name] = check
        report.passed = report.passed and check.passed

    return report


def clear_preflight_cache() -> None:
    """Clear the global preflight cache.

    Useful for testing or when tool configurations change.

    Examples:
        >>> clear_preflight_cache()
    """
    _clear_cache()


# Future enhancements for PR-3:
# - Result caching with TTL (BR_PREFLIGHT_TTL_SECONDS)
# - Parallel checking for batch operations
# - Integration with services/agent/preflight.py for deep validation
# - Network connectivity checks
# - License file validation
# - Resource availability checks (GPU, specific file paths)
