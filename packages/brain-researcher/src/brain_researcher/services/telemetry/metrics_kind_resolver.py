"""
Utility helpers for resolving orchestrator metrics job kinds.

The resolver maps requests/payloads onto a curated JobKind enum using a
configurable mapping so metrics remain low-cardinality and actionable.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

from .job_kind import JobKind

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = PROJECT_ROOT / "configs" / "metrics" / "kinds.yaml"

DEFAULT_PIPELINE_TO_KIND: Dict[str, str] = {
    "glm_first_level": JobKind.GLM.value,
    "glm_second_level": JobKind.GLM.value,
    "glm": JobKind.GLM.value,
    "connectivity_rest": JobKind.CONNECTIVITY.value,
    "connectivity": JobKind.CONNECTIVITY.value,
    "neuromaps_parcellate": JobKind.PARCELLATION.value,
    "parcellation": JobKind.PARCELLATION.value,
    "registration_mni": JobKind.REGISTRATION.value,
    "registration": JobKind.REGISTRATION.value,
    "mriqc": JobKind.QC.value,
    "kg_ingest_": JobKind.KG_INGEST.value,
    "kg_query": JobKind.KG_QUERY.value,
    "render_3d": JobKind.RENDER_3D.value,
    "download": JobKind.FILE_IO.value,
    "upload": JobKind.FILE_IO.value,
    "planner": JobKind.PLANNER.value,
}

DEFAULT_TOOL_TO_KIND: Dict[str, str] = {
    "fsl-feat": JobKind.GLM.value,
    "fitlins": JobKind.GLM.value,
    "nilearn-firstlevel": JobKind.GLM.value,
    "afni-3dttest": JobKind.GLM.value,
    "neuromaps": JobKind.PARCELLATION.value,
    "fmriprep": JobKind.REGISTRATION.value,
    "ants_registration": JobKind.REGISTRATION.value,
    "mriqc": JobKind.QC.value,
    "niclip": JobKind.EMBEDDING.value,
    "neurokg": JobKind.KG_QUERY.value,
}


def _normalize_kind(value: Optional[str]) -> str:
    if not value:
        return JobKind.OTHER.value
    value = value.lower()
    try:
        return JobKind(value).value
    except ValueError:
        logger.debug("Unknown job kind '%s' – defaulting to %s", value, JobKind.OTHER.value)
        return JobKind.OTHER.value


def _sanitize_mapping(raw: Mapping[str, Any]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for key, raw_kind in raw.items():
        if not key:
            continue
        sanitized[key.lower()] = _normalize_kind(str(raw_kind) if raw_kind is not None else None)
    return sanitized


@lru_cache(maxsize=1)
def load_job_kind_mapping() -> Dict[str, Dict[str, str]]:
    """
    Load the pipeline/tool mapping used for resolving job kinds.

    Returns a dict with keys ``pipeline`` and ``tool``.
    """
    pipeline_map = dict(DEFAULT_PIPELINE_TO_KIND)
    tool_map = dict(DEFAULT_TOOL_TO_KIND)

    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
            pipeline_map.update(_sanitize_mapping(data.get("pipeline_to_kind", {})))
            tool_map.update(_sanitize_mapping(data.get("tool_to_kind", {})))
        except Exception as exc:  # pragma: no cover - best-effort logging
            logger.warning("Failed to load metrics kind config at %s: %s", CONFIG_PATH, exc)

    return {"pipeline": pipeline_map, "tool": tool_map}


def _match_pipeline(name: Optional[str], mapping: Mapping[str, str]) -> Optional[str]:
    if not name:
        return None
    candidate = name.lower()
    if candidate in mapping:
        return mapping[candidate]

    # Prefix matching (keys ending in '_')
    for key, kind in mapping.items():
        if key.endswith("_") and candidate.startswith(key):
            return kind
    return None


def _extract_pipeline(request: Any, payload: Mapping[str, Any], metadata: Mapping[str, Any]) -> Optional[str]:
    if request:
        pipeline = getattr(request, "pipeline", None)
        if pipeline:
            return getattr(pipeline, "value", str(pipeline)).lower()
    pipeline = metadata.get("pipeline") or payload.get("pipeline")
    if isinstance(pipeline, str):
        return pipeline.lower()
    return None


def _extract_canonical_op(request: Any, payload: Mapping[str, Any], metadata: Mapping[str, Any]) -> Optional[str]:
    op = None
    if request:
        op = getattr(request, "canonical_op", None)
    if not op:
        op = metadata.get("canonical_op") or payload.get("canonical_op")

    if isinstance(op, Mapping):
        for key in ("name", "id", "operation", "op"):
            if key in op and isinstance(op[key], str):
                return op[key].lower()
    elif isinstance(op, str):
        return op.lower()
    return None


def _extract_tool(metadata: Mapping[str, Any], payload: Mapping[str, Any], parameters: Mapping[str, Any]) -> Optional[str]:
    tool = parameters.get("tool") or parameters.get("tool_name")
    tool = tool or metadata.get("tool_name")
    tool = tool or payload.get("tool_name")
    if isinstance(tool, str) and tool:
        return tool.lower()
    return None


def resolve_job_kind(
    request: Any = None,
    payload: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    Resolve the JobKind label for the given request/payload.

    Args:
        request: Optional RunRequest (or compatible object)
        payload: Serialized job payload (e.g., from JobStore)
        metadata: Metadata dict associated with the job/request

    Returns:
        A JobKind enum value as string.
    """
    payload = payload or {}
    metadata = metadata or payload.get("metadata") or {}
    parameters = metadata.get("parameters") or payload.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        parameters = {}

    mapping = load_job_kind_mapping()
    pipeline_name = _extract_pipeline(request, payload, metadata)
    canonical_op = _extract_canonical_op(request, payload, metadata)

    for key in (pipeline_name, canonical_op):
        resolved = _match_pipeline(key, mapping["pipeline"])
        if resolved:
            return resolved

    tool_name = _extract_tool(metadata, payload, parameters)
    if tool_name:
        resolved_tool = mapping["tool"].get(tool_name)
        if resolved_tool:
            return resolved_tool
        return JobKind.AGENT_TOOL.value

    # Fallback to planner jobs if canonical op requested without mapping.
    if canonical_op:
        return JobKind.PLANNER.value

    return JobKind.OTHER.value


def reset_job_kind_cache() -> None:
    """Utility for tests to clear cached config state."""
    load_job_kind_mapping.cache_clear()
