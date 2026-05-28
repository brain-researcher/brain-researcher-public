"""Vocabulary helpers for NeuroKG task and concept mapping."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import get_data_root

logger = logging.getLogger(__name__)

VOCAB_PATH = get_data_root() / "vocab" / "ca_topics_level0_v2.json"
EDGES_PATH = get_data_root() / "graphs" / "task_concept_edges.json"

_niclip_mapper = None


def _get_niclip_mapper() -> Any | None:
    """Get the lazily loaded NiCLIP task mapper."""

    global _niclip_mapper
    if _niclip_mapper is None:
        try:
            from brain_researcher.services.neurokg.etl.mappers.niclip_task_mapper import (
                get_mapper,
            )

            _niclip_mapper = get_mapper()
            logger.info("Loaded NiCLIP task mapper for vocab_loader")
        except Exception as exc:  # pragma: no cover - optional data dependency
            logger.warning("Could not load NiCLIP mapper: %s", exc)
    return _niclip_mapper


def _load_json_list(path: Path, *, label: str) -> list[dict[str, Any]]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    logger.warning("%s file not found at %s", label, path)
    return []


def load_vocab() -> list[dict[str, Any]]:
    """Load the Level-0 Cognitive Atlas topic vocabulary from JSON."""

    return _load_json_list(VOCAB_PATH, label="Vocab")


def load_task_concept_edges() -> list[dict[str, Any]]:
    """Load task-to-concept edges from JSON."""

    return _load_json_list(EDGES_PATH, label="Edges")


def id2level0() -> dict[str, str]:
    """Return a mapping from concept id to Level-0 topic/domain."""

    return {item["id"]: item["level0"] for item in load_vocab()}


def task2concept() -> dict[str, set[str]]:
    """Return a mapping from task id to concept ids."""

    mapping: dict[str, set[str]] = {}
    for edge in load_task_concept_edges():
        mapping.setdefault(edge["task_id"], set()).add(edge["concept_id"])
    return mapping


def id2name() -> dict[str, str]:
    """Return a mapping from concept id to name."""

    return {item["id"]: item["name"] for item in load_vocab()}


def get_task_concepts(task_name: str) -> list[str]:
    """Get concepts associated with a task using NiCLIP data."""

    mapper = _get_niclip_mapper()
    if mapper:
        return mapper.get_task_concepts(task_name)
    return []


def get_task_process(task_name: str) -> str | None:
    """Get the primary cognitive process id for a task."""

    mapper = _get_niclip_mapper()
    if mapper:
        return mapper.get_primary_process(task_name)
    return None


def get_task_process_name(task_name: str) -> str | None:
    """Get the human-readable primary process name for a task."""

    mapper = _get_niclip_mapper()
    if mapper:
        process_id = mapper.get_primary_process(task_name)
        if process_id:
            return mapper.get_process_name(process_id)
    return None


def get_concept_process(concept_name: str) -> str | None:
    """Get the cognitive process id for a concept."""

    mapper = _get_niclip_mapper()
    if mapper and hasattr(mapper, "concept_to_process"):
        return mapper.concept_to_process.get(concept_name)
    return None


def get_process_tasks(process_id: str) -> list[str]:
    """Get all tasks belonging to a cognitive process."""

    mapper = _get_niclip_mapper()
    if mapper:
        return mapper.get_process_tasks(process_id)
    return []


def search_similar_tasks(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Search for similar tasks based on task-name similarity."""

    mapper = _get_niclip_mapper()
    if mapper:
        results = mapper.search_similar_tasks(query, top_k)
        return [{"task": task, "score": score} for task, score in results]
    return []
