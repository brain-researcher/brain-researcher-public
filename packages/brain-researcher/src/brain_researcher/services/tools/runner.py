"""Lightweight helper to execute tools by id (developer/CLI use).

This bridges the gap between the ToolRegistry API and ad-hoc scripts by:
- Instantiating a light ToolRegistry
- Normalizing a few common parameter aliases (e.g., bold_file -> img)
- Returning the underlying ToolResult

It is intentionally minimal to avoid pulling in agent/runtime layers.
"""

from __future__ import annotations

import re
import sys
import traceback
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import get_outputs_root
from brain_researcher.services.mcp.execution_recipes import materialize_execution_pack
from brain_researcher.services.tools.execution_policy import (
    ExecutionPolicyError,
    enforce_allowed_paths,
    network_guard,
)
from brain_researcher.services.tools.spec import spec_from_tool
from brain_researcher.services.tools.tool_base import ToolResult
from brain_researcher.services.tools.tool_registry import ToolRegistry


def _purge_editable_finder():
    """Remove editable egg-link path hook for brain_researcher if present.

    When an older editable install leaves an entry like
    '__editable__.brain_researcher-0.0.finder.__path_hook__' on sys.path, it
    can shadow the worktree modules. This ensures the current worktree takes
    precedence when runner is imported explicitly.
    """

    sys.path[:] = [p for p in sys.path if "__editable__.brain_researcher" not in p]


_purge_editable_finder()


def _normalize_params(tool_id: str, params: MutableMapping[str, Any]) -> None:
    """Apply small alias fixes so legacy field names still work."""

    if tool_id == "extract_timeseries":
        # Common aliases from earlier scripts
        if "bold_file" in params and "img" not in params:
            params["img"] = params.pop("bold_file")
        if "confounds_file" in params and "confounds" not in params:
            params["confounds"] = params.pop("confounds_file")
        if "mask" in params and "mask_img" not in params:
            params["mask_img"] = params["mask"]

    if tool_id == "seed_based_fc":
        if "seed" in params and "seed_coords" not in params:
            params["seed_coords"] = params.pop("seed")


def _slugify_tool_id(tool_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(tool_id or "").strip())
    return slug.strip("._-") or "tool"


def _default_execution_pack_dir(tool_id: str, params: Mapping[str, Any]) -> Path:
    for key in ("output_dir", "work_dir"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser().resolve() / "execution_pack"

    for key in ("output_file", "img", "timeseries", "atlas"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser().resolve().parent / "execution_pack"

    return (
        get_outputs_root()
        / "execution_packs"
        / f"{_slugify_tool_id(tool_id)}_execution_pack"
    )


def _attach_execution_pack_metadata(
    result: ToolResult,
    *,
    tool_id: str,
    params: Mapping[str, Any],
    execution_pack_dir: str | None,
    execution_pack_target: str | None,
) -> ToolResult:
    try:
        pack_info = materialize_execution_pack(
            tool_id,
            dict(params),
            execution_pack_dir or _default_execution_pack_dir(tool_id, params),
            target_runtime=execution_pack_target,
        )
    except Exception as exc:
        metadata = dict(result.metadata or {})
        metadata["execution_pack_error"] = str(exc)
        result.metadata = metadata
        return result

    metadata = dict(result.metadata or {})
    metadata["execution_pack"] = pack_info
    result.metadata = metadata
    result_data = dict(result.data or {})
    result_data.setdefault("execution_pack", pack_info)
    result.data = result_data
    return result


def _coerce_tool_result(result: Any) -> ToolResult:
    if isinstance(result, ToolResult):
        return result
    status = getattr(result, "status", None)
    if status is not None:
        return ToolResult(
            status=str(status),
            data=getattr(result, "data", None),
            error=getattr(result, "error", None),
            metadata=getattr(result, "metadata", None),
        )
    return ToolResult(status="success", data=result)


def execute_tool(
    tool_id: str,
    params: Mapping[str, Any],
    *,
    emit_execution_pack: bool = True,
    execution_pack_dir: str | None = None,
    execution_pack_target: str | None = None,
) -> ToolResult:
    """Execute a registered tool by id with the given parameters.

    Example:
        res = execute_tool("extract_timeseries", {"img": "bold.nii.gz", "atlas": "aal.nii"})
    """

    registry = ToolRegistry.from_env(light_mode=True)
    tool = registry.get_tool(tool_id)
    if tool is None:
        return ToolResult(status="error", error=f"Tool not found: {tool_id}")

    params = dict(params)  # mutable copy
    _normalize_params(tool_id, params)

    # Get tool spec for policy enforcement
    spec = spec_from_tool(tool)

    # Enforce filesystem policy
    try:
        work_dir = params.get("work_dir")
        output_dir = params.get("output_dir")
        if spec:
            enforce_allowed_paths(
                spec, params, work_dir=work_dir, output_dir=output_dir
            )
    except ExecutionPolicyError as e:
        return ToolResult(
            status="error",
            error="execution_policy_violation",
            data={"policy_issues": e.issues},
        )

    # Execute tool with network guard
    try:
        with network_guard(spec):
            result = tool._run(**params)
        tool_result = _coerce_tool_result(result)
        if emit_execution_pack:
            return _attach_execution_pack_metadata(
                tool_result,
                tool_id=tool_id,
                params=params,
                execution_pack_dir=execution_pack_dir,
                execution_pack_target=execution_pack_target,
            )
        return tool_result
    except ExecutionPolicyError as e:
        return ToolResult(
            status="error",
            error="execution_policy_violation",
            data={"policy_issues": e.issues},
        )
    except Exception as exc:  # pragma: no cover
        tb = traceback.format_exc()
        return ToolResult(status="error", error=str(exc), data={"traceback": tb})


__all__ = ["execute_tool"]
