"""Bridge utilities for accessing MCP tool metadata.

Relocated from ``services/agent/tool_metadata_bridge`` into the shared layer so
that ``services/tools`` can depend on the metadata helpers without a
tools -> agent back-edge. The original agent module re-exports everything here.
"""

from __future__ import annotations

from copy import deepcopy
from functools import cache
from typing import Any

# MCP catalog removed; keep empty placeholders for compatibility
iter_tool_definitions = None
TOOL_METADATA: dict[str, dict[str, Any]] = {
    "bidsapp.fmriprep.run": {
        "resource_hints": {"cpu": 4, "mem_gb": 16, "gpu": 0},
    },
    "fitlins": {
        "examples": [
            {
                "bids_dir": "/data/bids",
                "output_dir": "/data/derivatives/fitlins",
                "analysis_level": "first",
            }
        ],
    },
}


def _normalize(name: str) -> str:
    return name.replace("-", ".").replace("_", ".").lower()


@cache
def _base_metadata() -> dict[str, dict[str, Any]]:
    """Collect metadata from registered tools and supplemental definitions."""
    metadata: dict[str, dict[str, Any]] = {}

    if iter_tool_definitions:
        try:
            for tool in iter_tool_definitions():
                name = tool.get("name")
                if not name:
                    continue
                payload: dict[str, Any] = {}
                resource_hints = tool.get("resource_hints")
                if resource_hints:
                    payload["resource_hints"] = resource_hints
                examples = tool.get("examples")
                if examples:
                    payload["examples"] = examples
                input_schema = tool.get("input_schema")
                if isinstance(input_schema, dict) and input_schema.get("examples"):
                    payload.setdefault("examples", input_schema["examples"])
                output_schema = tool.get("output_schema")
                if isinstance(output_schema, dict) and output_schema.get("examples"):
                    payload.setdefault("output_examples", output_schema["examples"])
                if payload:
                    metadata[name] = payload
        except Exception:
            pass

    for key, payload in TOOL_METADATA.items():
        target = metadata.setdefault(key, {})
        for field, value in payload.items():
            target.setdefault(field, value)

    return metadata


@cache
def _metadata_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for key, payload in _base_metadata().items():
        normalized = _normalize(key)
        index.setdefault(normalized, payload)
        # Add segment aliases for looser matching
        for segment in normalized.split("."):
            if len(segment) < 3:
                continue
            index.setdefault(segment, payload)
    return index


def _score_match(candidate: str, target: str) -> int:
    if candidate == target:
        return 100
    if candidate in target:
        return len(candidate)
    if target in candidate:
        return len(target)
    return 0


def get_tool_metadata(tool_name: str) -> dict[str, Any]:
    """Return MCP metadata for the closest matching tool."""
    if not tool_name:
        return {}

    target = _normalize(tool_name)
    index = _metadata_index()

    if target in index:
        return deepcopy(index[target])

    best_score = 0
    best_payload: dict[str, Any] | None = None
    for alias, payload in index.items():
        score = _score_match(alias, target)
        if score > best_score:
            best_score = score
            best_payload = payload

    return deepcopy(best_payload) if best_payload else {}


def get_resource_hints(tool_name: str) -> dict[str, Any]:
    """Return resource hints for a tool if available."""
    metadata = get_tool_metadata(tool_name)
    hints = metadata.get("resource_hints") if metadata else None
    return deepcopy(hints) if hints else {}


def get_example_payload(tool_name: str) -> dict[str, Any] | None:
    """Return the first input example for a tool."""
    metadata = get_tool_metadata(tool_name)
    examples = metadata.get("examples") if metadata else None
    if not isinstance(examples, list) or not examples:
        return None
    first = examples[0]
    return deepcopy(first) if isinstance(first, dict) else None


def get_output_examples(tool_name: str) -> list | None:
    """Return output schema examples for a tool."""
    metadata = get_tool_metadata(tool_name)
    output_examples = metadata.get("output_examples") if metadata else None
    if isinstance(output_examples, list) and output_examples:
        return deepcopy(output_examples)
    return None
