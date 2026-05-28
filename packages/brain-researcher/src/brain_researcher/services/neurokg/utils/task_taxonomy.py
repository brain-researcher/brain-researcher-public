"""Utilities for matching task labels to canonical taxonomy entities."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from brain_researcher.semantics.taxonomy.matcher import TaskMatcher, normalize_text

logger = logging.getLogger(__name__)

_PAREN_SPLIT = re.compile(r"[()]+")
_TOKEN_SPLIT = re.compile(r"[/,;]")


def _flatten_task_aliases(task_record: dict[str, Any]) -> Iterable[str]:
    """Yield alias-like strings for a Task node."""
    if not task_record:
        return []

    aliases = []
    for key in ("name", "label"):
        value = task_record.get(key)
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                aliases.append(trimmed)

    for field in ("alias", "aliases"):
        value = task_record.get(field)
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                aliases.append(candidate)
        elif isinstance(value, list | tuple | set):
            for item in value:
                if not item:
                    continue
                candidate = str(item).strip()
                if candidate:
                    aliases.append(candidate)

    seen: set[str] = set()
    for item in aliases:
        normalized = normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        yield item


@dataclass
class TaskMatchResult:
    """Structure describing a taxonomy or fallback match."""

    match: dict[str, Any]
    method: str
    fallback_node_id: str | None = None


class TaskTaxonomyResolver:
    """Helper that maps task labels to canonical Task nodes."""

    def __init__(
        self,
        db,
        matcher: TaskMatcher | None = None,
        *,
        allow_name_fallback: bool = True,
    ):
        self.db = db
        self.allow_name_fallback = allow_name_fallback and db is not None
        if matcher is not None:
            self.matcher = matcher
        else:
            try:
                self.matcher = TaskMatcher()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "TaskMatcher initialization failed; taxonomy matching will use name fallback only: %s",
                    exc,
                )
                self.matcher = None

        self._name_index: dict[str, str] = {}
        self.stats: dict[str, int] = {
            "canonical_created": 0,
            "taxonomy_matches": 0,
            "fallback_matches": 0,
        }

        if self.allow_name_fallback:
            self._bootstrap_name_index()

    # ------------------------------------------------------------------ Matching
    def match_label(self, label: str) -> TaskMatchResult | None:
        """Match a raw task label using taxonomy rules with fallback."""
        if not label:
            return None

        cleaned = label.strip()
        if not cleaned or cleaned == "?" or cleaned.lower().startswith("many tasks"):
            return None

        taxonomy_match = self._try_match_label(cleaned)
        if taxonomy_match:
            self.stats["taxonomy_matches"] += 1
            taxonomy_match["match_method"] = "taxonomy_rule"
            return TaskMatchResult(match=taxonomy_match, method="taxonomy_rule")

        fallback_match = self._fallback_task_lookup(cleaned)
        if fallback_match:
            self.stats["fallback_matches"] += 1
            fallback_match["match_method"] = "name_lookup"
            fallback_node = fallback_match.pop("_fallback_node_id", None)
            return TaskMatchResult(
                match=fallback_match, method="name_lookup", fallback_node_id=fallback_node
            )

        return None

    def ensure_canonical_task(self, match_result: TaskMatchResult) -> str | None:
        """Ensure a canonical Task node exists for the match and return its node id."""
        if not match_result:
            return None

        resolved_node_id = self._resolve_existing_task_node_id(match_result.match)
        if resolved_node_id:
            family_payload = self._extract_family_payload(match_result.match)
            if family_payload:
                self._ensure_task_family_link(resolved_node_id, family_payload)
            canonical_label = str(match_result.match.get("label") or "").strip()
            normalized = normalize_text(canonical_label)
            if normalized:
                self._register_name(normalized, resolved_node_id)
            return resolved_node_id

        if match_result.fallback_node_id:
            return match_result.fallback_node_id

        match = match_result.match
        canonical_label = match.get("label")
        if not canonical_label:
            return None

        normalized = normalize_text(canonical_label)
        if not normalized:
            return None

        existing = self._name_index.get(normalized)
        if existing:
            return existing

        canonical_id = match.get("canonical_id")
        node_id = (canonical_id or canonical_label).replace(":", "__")

        properties = {
            "id": canonical_id or node_id,
            "name": canonical_label,
            "source": "taxonomy_surface_rules",
            "canonical_id": canonical_id,
        }
        family_payload = self._extract_family_payload(match)
        if family_payload:
            properties["family_id"] = family_payload["family_id"]
            subfamily_id = family_payload.get("subfamily_id")
            if subfamily_id:
                properties["subfamily_id"] = subfamily_id

        taxonomy_rule = match.get("source_rule") or {}
        if taxonomy_rule.get("pattern"):
            properties["taxonomy_pattern"] = taxonomy_rule["pattern"]
        if taxonomy_rule.get("tags"):
            properties["taxonomy_tags"] = taxonomy_rule["tags"]

        created_node_id = self.db.create_node("Task", properties, node_id=node_id)
        if family_payload:
            self._ensure_task_family_link(created_node_id, family_payload)
        self._register_name(normalized, created_node_id)
        self.stats["canonical_created"] += 1
        return created_node_id

    # ------------------------------------------------------------------ Helpers
    def _bootstrap_name_index(self) -> None:
        for node_id, data in self.db.find_nodes("Task"):
            for alias in _flatten_task_aliases(data):
                normalized = normalize_text(alias)
                if normalized and normalized not in self._name_index:
                    self._name_index[normalized] = node_id

    def _register_name(self, normalized: str, node_id: str) -> None:
        if normalized and node_id:
            self._name_index.setdefault(normalized, node_id)

    def _resolve_existing_task_node_id(self, match: dict[str, Any]) -> str | None:
        if self.db is None:
            return None

        entity = match.get("entity")
        entity_payload = entity if isinstance(entity, dict) else {}
        links = entity_payload.get("links")
        link_payload = links if isinstance(links, dict) else {}

        node_ids_to_try = [
            str(link_payload.get("cogat") or "").strip(),
            str(match.get("canonical_id") or "").strip(),
        ]
        for candidate in node_ids_to_try:
            if not candidate:
                continue
            existing = self.db.get_node(candidate)
            if existing and "Task" in existing.get("labels", []):
                return candidate

        property_lookups = [
            ("task_id", str(link_payload.get("cogat") or "").strip()),
            ("canonical_id", str(match.get("canonical_id") or "").strip()),
            ("name", str(match.get("label") or "").strip()),
        ]
        for key, value in property_lookups:
            if not value:
                continue
            existing_nodes = self.db.find_nodes("Task", {key: value})
            if existing_nodes:
                return existing_nodes[0][0]
        return None

    @staticmethod
    def _extract_family_payload(match: dict[str, Any]) -> dict[str, str] | None:
        entity = match.get("entity")
        entity_payload = entity if isinstance(entity, dict) else {}

        family_id = str(
            match.get("family_id") or entity_payload.get("family_id") or ""
        ).strip()
        if not family_id:
            return None

        subfamily_id = str(
            match.get("subfamily_id") or entity_payload.get("subfamily_id") or ""
        ).strip()

        family_label = str(
            match.get("family_label") or entity_payload.get("family_label") or family_id
        ).strip()
        subfamily_label = str(
            match.get("subfamily_label")
            or entity_payload.get("subfamily_label")
            or subfamily_id
        ).strip()
        family_description = str(
            match.get("family_description") or entity_payload.get("family_description") or ""
        ).strip()

        return {
            "family_id": family_id,
            "subfamily_id": subfamily_id,
            "family_label": family_label,
            "subfamily_label": subfamily_label,
            "family_description": family_description,
        }

    def _ensure_task_family_link(self, task_node_id: str, family_payload: dict[str, str]) -> None:
        family_id = family_payload["family_id"]

        existing_family = self.db.find_nodes(
            "TaskFamily",
            {"id": family_id},
        )
        if existing_family:
            family_node_id = existing_family[0][0]
        else:
            family_node_id = family_id
            family_props = {
                "id": family_id,
                "name": family_payload.get("family_label") or family_id,
                "family_id": family_id,
                "family_label": family_payload.get("family_label") or family_id,
                "family_description": family_payload.get("family_description") or "",
                "source": "taxonomy_surface_rules",
            }
            self.db.create_node("TaskFamily", family_props, node_id=family_node_id)

        existing_rel = []
        if hasattr(self.db, "find_relationships"):
            existing_rel = self.db.find_relationships(
                start_node=task_node_id,
                end_node=family_node_id,
                rel_type="BELONGS_TO_FAMILY",
            )
        if not existing_rel:
            rel_props: dict[str, Any] = {"source": "taxonomy_surface_rules"}
            subfamily_id = family_payload.get("subfamily_id")
            if subfamily_id:
                rel_props["subfamily_id"] = subfamily_id
                rel_props["subfamily_label"] = (
                    family_payload.get("subfamily_label") or subfamily_id
                )
            self.db.create_relationship(
                task_node_id,
                family_node_id,
                "BELONGS_TO_FAMILY",
                rel_props,
            )

    def _try_match_label(self, label: str) -> dict[str, Any] | None:
        if not self.matcher:
            return None

        normalized_text = normalize_text(label)
        match = self.matcher.match(normalized_text)
        if match:
            return match

        if "(" in label and ")" in label:
            for part in _PAREN_SPLIT.split(label):
                part = part.strip()
                if not part:
                    continue
                maybe = self.matcher.match(normalize_text(part))
                if maybe:
                    return maybe

        for token in _TOKEN_SPLIT.split(label):
            token = token.strip()
            if len(token) < 3:
                continue
            maybe = self.matcher.match(normalize_text(token))
            if maybe:
                return maybe
        return None

    def _fallback_task_lookup(self, label: str) -> dict[str, Any] | None:
        if not self.allow_name_fallback:
            return None

        normalized = normalize_text(label)
        if not normalized:
            return None

        node_id = self._name_index.get(normalized)
        if not node_id:
            return None

        node_data = self.db.get_node(node_id)
        canonical_id = None
        canonical_label = label
        if node_data:
            canonical_label = node_data.get("name") or canonical_label
            canonical_id = node_data.get("canonical_id") or node_data.get("id")

        return {
            "match_string": label,
            "canonical_id": canonical_id,
            "label": canonical_label,
            "type": "Task",
            "parameters": {},
            "confidence": 0.5,
            "source_rule": {"pattern": "fallback-name-match"},
            "_fallback_node_id": node_id,
        }


__all__ = [
    "TaskTaxonomyResolver",
    "TaskMatchResult",
    "_flatten_task_aliases",
]
