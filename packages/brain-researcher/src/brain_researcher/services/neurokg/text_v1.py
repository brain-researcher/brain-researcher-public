"""Shared helpers for BR-KG text_v1 node text representations."""

from __future__ import annotations

from typing import Any

DEFAULT_TEXT_V1_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TEXT_V1_TEMPLATE_VERSION = "node_text_v1"


def create_text_v1_representation(node_type: str, properties: dict[str, Any]) -> str:
    """Build the canonical text_v1 representation for a BR-KG node."""

    text_parts: list[str] = [f"[{node_type}]"]

    def _extend_values(keys: list[str]) -> None:
        for key in keys:
            value = properties.get(key)
            if isinstance(value, list):
                text_parts.extend(str(item) for item in value if item)
            elif isinstance(value, str):
                text_parts.append(value)

    _extend_values(["name", "label", "title", "id"])
    _extend_values(["aliases", "alias", "synonyms", "keywords"])
    _extend_values(["short_description", "description", "definition", "summary"])

    if node_type in {"Task", "TaskDef", "TaskSpec"}:
        _extend_values(["task_family", "cognitive_paradigm", "task_type", "modality"])
        _extend_values(["contrasts", "conditions", "stimuli", "response"])
    elif node_type in {"Concept", "Construct"}:
        _extend_values(["domain", "subdomain", "category"])
    elif node_type in {"Tool", "ToolFamily"}:
        _extend_values(["tool_name", "family", "category", "modality", "function"])
        _extend_values(["confounds", "smoothing", "ica", "pipeline", "version"])
    elif node_type == "Dataset":
        _extend_values(["dataset_id", "tasks", "modalities", "source"])
        n_subjects = properties.get("n_subjects") or properties.get("subjects")
        if n_subjects is not None:
            text_parts.append(f"n_subjects={n_subjects}")
    elif node_type in {"Region", "BrainRegion"}:
        _extend_values(["region", "label", "description"])
    elif node_type == "Publication":
        _extend_values(["title", "abstract", "keywords"])

    return " ".join(part for part in text_parts if part)
