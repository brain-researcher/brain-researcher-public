"""Load default tool allowlist for the Agent UI API.

This provides a single place to read the curated tool list from
configs/catalog/chat_tools.yaml when AGENT_TOOL_ALLOWLIST is not set.

Keeping the YAML as the source of truth lets us tune the exposed tool
surface without touching code and keeps unit tests stable.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.tools.spec import infer_requires_runtime

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
        # Keep canonical runtime ids discoverable on exposed search surfaces even
        # when their execution backend remains runtime-gated by default.
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
    "python.fmriprep.",
    "python.mriqc.",
    "python.qsiprep.",
    "python.xcpd.",
    "qsiprep_",
    "run_",
    "workflow_",
    "xcpd_",
)


@lru_cache(maxsize=1)
def _all_toolspecs_by_name() -> dict[str, Any]:
    """Best-effort toolspec index for hybrid local-first blocking."""

    try:
        from brain_researcher.services.tools.catalog_loader import load_tool_specs
    except Exception:
        return {}

    try:
        loaded = load_tool_specs(force_reload=False, exposed_only=False)
    except Exception:
        return {}

    if isinstance(loaded, dict):
        items = loaded.values()
    else:
        items = loaded

    indexed: dict[str, Any] = {}
    for spec in items:
        name = str(getattr(spec, "name", "") or "").strip().lower()
        if name:
            indexed[name] = spec
    return indexed


def _toolspec_local_first_blocked(lowered: str) -> bool:
    """Block known runtime-backed executors using tool metadata when available."""

    spec = _all_toolspecs_by_name().get(lowered)
    if spec is None:
        return False

    runtime = infer_requires_runtime(
        getattr(spec, "requires_runtime", None),
        backend=getattr(spec, "backend", None),
    )
    backend = str(getattr(spec, "backend", "") or "").strip().lower()
    if runtime == "container" or backend == "niwrap":
        return True
    return False


def _allow_remote_execution_tools() -> bool:
    return os.environ.get(
        "BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _allow_all_runtime_tools() -> bool:
    return os.environ.get(
        "BR_AGENT_ALLOW_ALL_RUNTIME_TOOLS", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def allow_remote_execution_tools_enabled() -> bool:
    """Return True when remote execution tools may be exposed to agents."""

    return _allow_remote_execution_tools()


def is_local_first_blocked_tool(tool_id: str) -> bool:
    """Return True when a tool should be hidden from agent auto-selection."""

    normalized = str(tool_id or "").strip()
    if not normalized or _allow_remote_execution_tools():
        return False
    lowered = normalized.lower()
    if lowered in _LOCAL_FIRST_ALLOWED_EXACT:
        return False
    if lowered in _LOCAL_FIRST_BLOCKED_EXACT:
        return True
    if any(lowered.startswith(prefix) for prefix in _LOCAL_FIRST_BLOCKED_PREFIXES):
        return True
    return _toolspec_local_first_blocked(lowered)


def filter_local_first_tool_ids(tool_ids: list[str]) -> list[str]:
    """Filter/normalize a tool list for local-first agent execution."""

    out: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        normalized = str(tool_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if is_local_first_blocked_tool(normalized):
            continue
        out.append(normalized)
    return out


def _canonicalize_runtime_tool_ids(tool_ids: list[str] | None) -> list[str]:
    if not tool_ids:
        return []

    try:
        from brain_researcher.services.tools.catalog_loader import (
            resolve_primary_runtime_tool_id,
        )
    except Exception:
        resolve_primary_runtime_tool_id = None  # type: ignore

    out: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        normalized = str(tool_id or "").strip()
        if not normalized:
            continue
        canonical = (
            resolve_primary_runtime_tool_id(normalized)
            if resolve_primary_runtime_tool_id
            else normalized
        )
        resolved = str(canonical or normalized).strip()
        if not resolved or resolved in seen:
            continue
        out.append(resolved)
        seen.add(resolved)
    return out


def resolve_runtime_tool_allowlist(
    env_tool_allowlist: list[str] | None,
    *,
    strict: bool | None = None,
) -> list[str] | None:
    """Merge env allowlist with curated chat tools under local-first rules."""

    if _allow_all_runtime_tools():
        return None

    chat_tools = _canonicalize_runtime_tool_ids(load_chat_tools_allowlist())

    if env_tool_allowlist is None:
        return chat_tools or None

    if not env_tool_allowlist:
        return []

    if strict is None:
        strict = os.getenv("AGENT_TOOL_ALLOWLIST_STRICT", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    if strict or not chat_tools:
        return filter_local_first_tool_ids(
            _canonicalize_runtime_tool_ids(list(env_tool_allowlist))
        )

    merged: list[str] = []
    seen: set[str] = set()
    for tool_id in [*env_tool_allowlist, *chat_tools]:
        normalized = str(tool_id or "").strip()
        if not normalized or normalized in seen:
            continue
        merged.append(normalized)
        seen.add(normalized)
    return filter_local_first_tool_ids(_canonicalize_runtime_tool_ids(merged))


def load_chat_tools_allowlist() -> list[str]:
    """Return the curated chat tool list from chat_tools.yaml.

    If the file is missing or empty, returns an empty list rather than
    raising, so callers can decide how to fallback (e.g., no allowlist).
    """

    # Optional override for testing / custom deployments
    override = os.environ.get("CHAT_TOOLS_PATH")
    if override:
        path = Path(override)
    else:
        path = resolve_from_config("catalog", "chat_tools.yaml")
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text()) or {}
    tools = data.get("chat_tools") or []
    # Normalise to list[str]
    normalized = [str(t).strip() for t in tools if str(t).strip()]
    return filter_local_first_tool_ids(_canonicalize_runtime_tool_ids(normalized))


def load_full_tool_allowlist(*, include_workflows: bool = True) -> list[str]:
    """Return the full catalog tool surface without chat/local-first pruning."""

    try:
        from brain_researcher.services.tools.catalog_loader import load_tool_specs
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("Unable to load tool catalog for diagnostic allowlist") from exc

    specs = load_tool_specs(
        force_reload=False,
        exposed_only=False,
        include_workflows=include_workflows,
    )
    tool_ids: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        tool_id = str(getattr(spec, "name", "") or "").strip()
        if not tool_id or tool_id in seen:
            continue
        tool_ids.append(tool_id)
        seen.add(tool_id)
    return tool_ids


def expand_plan_tool_ids(tool_ids: list[str] | None) -> list[str]:
    """Normalize plan-surface tool IDs onto runtime-canonical names."""

    return _canonicalize_runtime_tool_ids(tool_ids)


def resolve_plan_tool_allowlist(
    env_tool_allowlist: list[str] | None,
    *,
    allowlist_mode: str | None = None,
    strict: bool | None = None,
) -> list[str] | None:
    """Resolve a plan-surface allowlist.

    ``diagnostic`` mode widens the tool surface to the full catalog so benchmark
    routing can measure recall without the curated chat surface pruning it first.
    """

    mode = str(allowlist_mode or "").strip().lower()
    if mode == "diagnostic":
        return expand_plan_tool_ids(load_full_tool_allowlist())
    return expand_plan_tool_ids(
        resolve_runtime_tool_allowlist(env_tool_allowlist, strict=strict)
    )


__all__ = [
    "allow_remote_execution_tools_enabled",
    "filter_local_first_tool_ids",
    "expand_plan_tool_ids",
    "is_local_first_blocked_tool",
    "load_chat_tools_allowlist",
    "load_full_tool_allowlist",
    "resolve_runtime_tool_allowlist",
    "resolve_plan_tool_allowlist",
]
