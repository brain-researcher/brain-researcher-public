"""Link Neurostore/alias-matched tasks to Cognitive Atlas concepts via taxonomy data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path

logger = logging.getLogger(__name__)


@dataclass
class TaxonomySuggestion:
    """Container for a taxonomy-derived suggestion."""

    concept_id: str
    canonical_id: str
    match_label: str
    method: str
    source: str
    confidence: float
    rule_id: Optional[str]
    evidence: Dict[str, object]

    def relationship_properties(self) -> Dict[str, object]:
        props = {
            "source": self.source,
            "method": self.method,
            "confidence": float(self.confidence),
            "canonical_id": self.canonical_id,
            "match_label": self.match_label,
        }
        if self.rule_id:
            props["rule_id"] = self.rule_id
        if self.evidence:
            props["evidence_json"] = self.evidence
        return props


class TaxonomyLinker:
    """Generates Concept suggestions for tasks matched via the taxonomy."""

    def __init__(
        self,
        entities_path: Optional[str | Path] = None,
        cao_map_path: Optional[str | Path] = None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[5]
        taxonomy_dir = repo_root / "semantics" / "taxonomy"
        legacy_cao_map = repo_root / "services" / "br_kg" / "mappings" / "cao_to_trm.yaml"
        self.entities_path = Path(entities_path) if entities_path else taxonomy_dir / "entities.json"
        self.cao_map_path = resolve_mapping_path(
            "cao_to_trm",
            requested_path=cao_map_path,
            fallback=legacy_cao_map,
            must_exist=False,
        )
        self.entities = self._load_entities()
        self._canonical_concepts = self._build_canonical_concept_map()
        self._cao_to_trm = self._load_cao_to_trm_map()

    # ------------------------------------------------------------------ public API
    def suggestions_for_task(self, task: Dict[str, object]) -> List[TaxonomySuggestion]:
        """Return suggestions for a single Neurostore task payload."""

        match = task.get("taxonomy_match") if isinstance(task, dict) else None
        if not isinstance(match, dict):
            return []
        canonical_id = match.get("canonical_id")
        if not canonical_id:
            return []

        concept_ids = self._canonical_concepts.get(canonical_id)
        if not concept_ids:
            return []

        method = match.get("match_method") or "taxonomy_rule"
        source = "taxonomy_rule"
        rule_info = match.get("source_rule") or {}
        rule_id = rule_info.get("id") or rule_info.get("pattern")
        confidence = self._resolve_confidence(match)
        match_label = (
            match.get("match_string")
            or task.get("name")
            or task.get("name_original")
            or ""
        )

        evidence = {"taxonomy": {"match": match}}

        suggestions: List[TaxonomySuggestion] = []
        for concept_id in concept_ids:
            resolved = self._resolve_cao_mapping(concept_id)
            suggestions.append(
                TaxonomySuggestion(
                    concept_id=resolved,
                    canonical_id=str(canonical_id),
                    match_label=str(match_label),
                    method=str(method),
                    source=source,
                    confidence=confidence,
                    rule_id=rule_id,
                    evidence=evidence,
                )
            )
        return suggestions

    def refresh(self) -> None:
        """Reload taxonomy entities and refresh derived maps."""
        self.entities = self._load_entities()
        self._canonical_concepts = self._build_canonical_concept_map()
        self._cao_to_trm = self._load_cao_to_trm_map()

    # ------------------------------------------------------------------ helpers
    def _load_entities(self) -> Dict[str, Dict[str, object]]:
        try:
            payload = json.loads(self.entities_path.read_text(encoding="utf-8"))
            return payload.get("entities", {})
        except FileNotFoundError:
            logger.warning("Taxonomy entities file not found at %s", self.entities_path)
            return {}
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load taxonomy entities: %s", exc)
            return {}

    def _build_canonical_concept_map(self) -> Dict[str, List[str]]:
        cache: Dict[str, List[str]] = {}
        for canonical_id in self.entities.keys():
            targets = self._resolve_concept_ids(canonical_id)
            if targets:
                cache[canonical_id] = sorted(targets)
        return cache

    def _resolve_concept_ids(
        self,
        entity_id: str,
        _visited: Optional[set[str]] = None,
    ) -> List[str]:
        entity = self.entities.get(entity_id)
        if not entity:
            return []

        if _visited is None:
            _visited = set()
        if entity_id in _visited:
            return []
        _visited.add(entity_id)

        concept_ids: List[str] = []
        links = entity.get("links") or {}
        cogat = links.get("cogat") if isinstance(links, dict) else None
        if cogat:
            concept_ids.append(str(cogat).lower())

        for measure_id in entity.get("measures", []) or []:
            concept_ids.extend(self._resolve_concept_ids(measure_id, _visited))

        return list(dict.fromkeys(concept_ids))

    def _resolve_confidence(self, match: Dict[str, object]) -> float:
        value = match.get("confidence")
        if isinstance(value, (int, float)):
            try:
                return float(value)
            except (TypeError, ValueError):  # pragma: no cover
                pass

        method = match.get("match_method") or "taxonomy_rule"
        if method == "taxonomy_rule":
            return 0.85
        if method == "alias_match":
            return 0.8
        return 0.75

    def _load_cao_to_trm_map(self) -> Dict[str, str]:
        try:
            if self.cao_map_path.exists():
                rows = yaml.safe_load(self.cao_map_path.read_text(encoding="utf-8")) or []
                mapping: Dict[str, str] = {}
                for row in rows:
                    cao_id = str(row.get("cao_id", "")).upper()
                    trm_id = row.get("trm_id")
                    if cao_id and trm_id:
                        mapping[cao_id] = trm_id
                return mapping
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load CAO→TRM map: %s", exc)
        return {}

    def _resolve_cao_mapping(self, concept_id: str) -> str:
        if not concept_id:
            return concept_id
        upper = concept_id.upper()
        if upper in self._cao_to_trm:
            return self._cao_to_trm[upper]
        entity = self.entities.get(concept_id)
        if entity:
            links = entity.get("links") or {}
            cao_id = links.get("cogat")
            if isinstance(cao_id, str):
                upper_cao = cao_id.upper()
                if upper_cao in self._cao_to_trm:
                    return self._cao_to_trm[upper_cao]
                return upper_cao
        return concept_id


def iter_taxonomy_suggestions(
    linker: TaxonomyLinker,
    tasks: Iterable[Dict[str, object]],
) -> Iterable[TaxonomySuggestion]:
    for task in tasks:
        for suggestion in linker.suggestions_for_task(task):
            yield suggestion
