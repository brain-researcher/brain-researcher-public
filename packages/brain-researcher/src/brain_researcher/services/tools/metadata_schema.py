"""Metadata vocab and validation helpers for ToolSpecs.

Used by registry/spec merge, validators, and router filtering.
"""

from __future__ import annotations

from typing import Dict, List

DOMAIN = {
    "fmri",
    "fmri.preproc",
    "fmri.glm",
    "fmri.connectivity",
    "fmri.qc",
    "fmri.viz",
    "dmri",
    "dmri.preproc",
    "dmri.modeling",
    "dmri.tractography",
    "dmri.connectome",
    "dmri.qc",
    "smri",
    "surface",
    "surface.recon",
    "surface.parcellation",
    "surface.workbench",
    "surface.viz",
    "surface.registration",
    "eeg",
    "ieeg",
    "pet",
    "clinical",
    "kg",
    "datasets",
    "jobs",
    "coding",
    "fs",
    "net",
    "viz",
    "meta",
    "realtime",
    "advanced",
    "specialized",
    "container",
    "mcp",
    "niwrap",
}

FUNCTION = {
    "preproc",
    "glm",
    "connectivity",
    "qc",
    "decoding",
    "meta",
    "visualization",
    "ingest",
    "search",
    "infer",
    "admin",
    "backend",
    "routing",
    "conversion",
    "report",
    "analysis",
    "simulation",
}

RUNTIME_KIND = {"python", "container", "mcp", "llm"}

RISK = {"safe", "dangerous", "external_net", "high_cost"}

EXPOSURE = {"chat", "pipeline", "cli", "advanced", "internal"}


def validate_metadata(meta: Dict) -> List[str]:
    """Return list of problems found in a metadata dict."""
    problems: List[str] = []
    d = meta or {}
    dom = d.get("domain")
    if dom not in DOMAIN:
        problems.append(f"invalid/missing domain: {dom}")
    func = d.get("function")
    if func not in FUNCTION:
        problems.append(f"invalid/missing function: {func}")
    rk = d.get("runtime_kind")
    if rk not in RUNTIME_KIND:
        problems.append(f"invalid/missing runtime_kind: {rk}")
    risk = d.get("risk")
    if risk not in RISK:
        problems.append(f"invalid/missing risk: {risk}")
    exposure = d.get("exposure")
    if exposure not in EXPOSURE:
        problems.append(f"invalid/missing exposure: {exposure}")
    tags = d.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        problems.append("tags must be a list[str]")
    if not tags:
        problems.append("tags empty")
    return problems


def normalize_tags(meta: Dict) -> List[str]:
    """Ensure tags include domain/function/runtime_kind/risk."""
    tags = set(meta.get("tags") or [])
    for key in ("domain", "function", "runtime_kind", "risk", "exposure"):
        val = meta.get(key)
        if val:
            tags.add(str(val))
    return sorted(tags)
