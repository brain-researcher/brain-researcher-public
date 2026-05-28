"""Helpers for linking Neurostore/OpenNeuro metadata to existing Neo4j constructs."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from brain_researcher.semantics.taxonomy.matcher import (
    ConceptMatcher,
    MatchCandidate,
    normalize_text,
)

logger = logging.getLogger(__name__)

MEASURES_THRESHOLD = 0.90
SUGGESTS_THRESHOLD = 0.75


def _safe_iter(value: Optional[Iterable[str]]) -> Iterable[str]:
    if not value:
        return []
    return value


class ConstructManager:
    """Resolve Concepts -> Processes (domains) and enforce IN_DOMAIN relationships."""

    def __init__(self, db) -> None:
        self.db = db
        self._process_index: Dict[str, Set[str]] = defaultdict(set)
        self._concept_process_index: Dict[str, Set[str]] = defaultdict(set)
        self._load_process_index()
        self._load_concept_process_index()

    # ------------------------------------------------------------------ loading
    def _load_process_index(self) -> None:
        query = (
            "MATCH (p:Process) "
            "RETURN p.id AS id, p.name AS name, "
            "coalesce(p.aliases, []) AS aliases, "
            "coalesce(p.synonyms, []) AS alt_labels"
        )
        try:
            result = self.db._run(query)
        except Exception as exc:  # pragma: no cover - Neo4j access errors
            logger.debug("Unable to load Process index: %s", exc)
            return

        try:
            for record in result:
                process_id = record.get("id") or record.get("name")
                if not process_id:
                    continue
                names: List[str] = []
                primary = record.get("name")
                if primary:
                    names.append(primary)
                for field in ("aliases", "alt_labels"):
                    entries = record.get(field) or []
                    if isinstance(entries, (list, tuple, set)):
                        names.extend(str(item) for item in entries if item)
                names.append(process_id)
                for name in names:
                    normalized = normalize_text(str(name))
                    if normalized:
                        self._process_index[normalized].add(str(process_id))
        finally:
            try:
                result.close()
            except Exception:  # pragma: no cover - best effort
                pass

    def _load_concept_process_index(self) -> None:
        query = (
            "MATCH (c:Concept)-[:CLASSIFIED_UNDER]->(p:Process) "
            "RETURN c.id AS concept_id, p.id AS process_id"
        )
        try:
            result = self.db._run(query)
        except Exception as exc:  # pragma: no cover - Neo4j access errors
            logger.debug("Unable to load Concept->Process map: %s", exc)
            return

        try:
            for record in result:
                concept_id = record.get("concept_id")
                process_id = record.get("process_id")
                if not concept_id or not process_id:
                    continue
                lowered = str(concept_id).lower()
                self._concept_process_index[lowered].add(str(process_id))
                self._concept_process_index[str(concept_id)].add(str(process_id))
        finally:
            try:
                result.close()
            except Exception:  # pragma: no cover - best effort
                pass

    # ------------------------------------------------------------------ lookups
    def process_ids_for_names(self, domains: Sequence[str]) -> Tuple[Set[str], List[str]]:
        matches: Set[str] = set()
        misses: List[str] = []
        for domain in domains:
            if not domain:
                continue
            normalized = normalize_text(str(domain))
            if not normalized:
                continue
            candidates = self._process_index.get(normalized)
            if candidates:
                matches.update(candidates)
            else:
                misses.append(domain)
        return matches, misses

    def process_ids_for_concepts(self, concept_ids: Iterable[str]) -> Set[str]:
        matches: Set[str] = set()
        for concept_id in concept_ids:
            if not concept_id:
                continue
            lowered = str(concept_id).lower()
            matches.update(self._concept_process_index.get(lowered, set()))
            matches.update(self._concept_process_index.get(str(concept_id), set()))
        return matches

    # ------------------------------------------------------------------ linking
    def link_entity_to_processes(
        self,
        entity_id: str,
        process_ids: Iterable[str],
        *,
        source: str,
        method: str,
        confidence: float = 0.85,
        relationship: str = "IN_DOMAIN",
    ) -> int:
        created = 0
        for process_id in sorted({pid for pid in process_ids if pid}):
            if self._relationship_exists(entity_id, process_id, relationship):
                continue
            rel_props = {
                "source": source,
                "method": method,
                "confidence": float(confidence),
            }
            try:
                if self.db.create_relationship(entity_id, process_id, relationship, rel_props):
                    created += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(
                    "Failed linking %s -> %s (%s): %s",
                    entity_id,
                    process_id,
                    relationship,
                    exc,
                )
        return created

    def _relationship_exists(self, start_id: str, end_id: str, rel_type: str) -> bool:
        try:
            existing = self.db.find_relationships(
                start_node=start_id,
                end_node=end_id,
                rel_type=rel_type,
            )
        except Exception:  # pragma: no cover - defensive
            return False
        return bool(existing)


class NeurostoreTaskLinker:
    """Attach Neurostore task metadata to existing Concept/Process nodes."""

    def __init__(
        self,
        db,
        *,
        source: str = "neurostore_metadata",
    ) -> None:
        self.db = db
        self.source = source
        self._concept_matcher = ConceptMatcher()
        self._construct_manager = ConstructManager(db)

    # ------------------------------------------------------------------ public
    def link_tasks(
        self,
        tasks: Sequence[Dict[str, object]],
        node_map: Dict[str, str],
    ) -> Dict[str, int]:
        stats = {
            "concept_links": 0,
            "domain_links": 0,
            "concept_misses": 0,
            "domain_misses": 0,
        }

        for task in tasks:
            task_uid = str(task.get("task_uid") or "")
            if not task_uid:
                continue
            node_key = f"neurostore_task:{task_uid}"
            node_id = node_map.get(node_key)
            if not node_id:
                continue

            concepts = task.get("concepts_original") or []
            matched_concepts, concept_created, concept_misses = self._link_concepts(
                node_id,
                concepts,
            )
            stats["concept_links"] += concept_created
            stats["concept_misses"] += concept_misses

            process_ids: Set[str] = set()
            if matched_concepts:
                process_ids.update(
                    self._construct_manager.process_ids_for_concepts(matched_concepts)
                )

            domains = task.get("domains_original") or []
            if domains:
                domain_matches, domain_misses = self._construct_manager.process_ids_for_names(
                    [str(domain) for domain in domains if domain]
                )
                process_ids.update(domain_matches)
                stats["domain_misses"] += len(domain_misses)

            if process_ids:
                created = self._construct_manager.link_entity_to_processes(
                    node_id,
                    process_ids,
                    source=self.source,
                    method="metadata",
                    confidence=0.9,
                )
                stats["domain_links"] += created

        return stats

    # ------------------------------------------------------------------ helpers
    def _link_concepts(
        self,
        task_node_id: str,
        concept_names: Iterable[object],
    ) -> Tuple[Set[str], int, int]:
        matched_concepts: Set[str] = set()
        created = 0
        misses = 0

        for raw_name in concept_names:
            name = str(raw_name or "").strip()
            if not name:
                continue

            candidates = self._concept_matcher.match_candidates(
                name,
                max_results=5,
                min_confidence=0.65,
            )

            linked = False
            for candidate in candidates:
                concept_id = self._resolve_concept_candidate(candidate)
                if not concept_id:
                    continue

                confidence = float(candidate.confidence)
                if confidence >= MEASURES_THRESHOLD:
                    rel_type = "MEASURES"
                elif confidence >= SUGGESTS_THRESHOLD:
                    rel_type = "SUGGESTS_MEASURES"
                else:
                    continue

                if self._relationship_exists(task_node_id, concept_id, rel_type):
                    linked = True
                    matched_concepts.add(concept_id)
                    break

                rel_props = {
                    "source": self.source,
                    "method": candidate.method,
                    "confidence": confidence,
                    "match_label": candidate.label,
                }
                if candidate.canonical_id:
                    rel_props["canonical_id"] = candidate.canonical_id
                if candidate.parameters:
                    rel_props["parameters_json"] = json.dumps(
                        candidate.parameters,
                        sort_keys=True,
                    )

                try:
                    if self.db.create_relationship(
                        task_node_id,
                        concept_id,
                        rel_type,
                        rel_props,
                    ):
                        created += 1
                        linked = True
                        matched_concepts.add(concept_id)
                        break
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug(
                        "Failed linking Neurostore task %s -> %s (%s): %s",
                        task_node_id,
                        concept_id,
                        rel_type,
                        exc,
                    )

            if not linked:
                misses += 1

        return matched_concepts, created, misses

    def _resolve_concept_candidate(self, candidate: MatchCandidate) -> Optional[str]:
        candidate_ids: List[str] = []
        if candidate.canonical_id:
            candidate_ids.extend(
                {
                    candidate.canonical_id,
                    candidate.canonical_id.lower(),
                    candidate.canonical_id.upper(),
                }
            )
        entity = candidate.entity or {}
        links = entity.get("links") or {}
        if isinstance(links, dict):
            for scheme, value in links.items():
                if not value:
                    continue
                candidate_ids.append(str(value))
                candidate_ids.append(f"{str(scheme).lower()}:{value}")

        for candidate_id in candidate_ids:
            node_id = self._find_concept_node_by_id(candidate_id)
            if node_id:
                return node_id

        node_id = self._find_concept_node_by_name(candidate.label)
        if node_id:
            return node_id

        return None

    def _find_concept_node_by_id(self, candidate_id: str) -> Optional[str]:
        if not candidate_id:
            return None
        try:
            nodes = self.db.find_nodes("Concept", {"id": candidate_id})
        except Exception:
            nodes = []

        if nodes:
            node = nodes[0]
            if isinstance(node, tuple):
                return str(node[0])
            if isinstance(node, dict):
                return str(node.get("id"))

        lowered = candidate_id.lower()
        try:
            nodes = self.db.find_nodes("Concept", {"id": lowered})
        except Exception:
            nodes = []
        if nodes:
            node = nodes[0]
            if isinstance(node, tuple):
                return str(node[0])
            if isinstance(node, dict):
                return str(node.get("id"))

        return None

    def _find_concept_node_by_name(self, label: str) -> Optional[str]:
        if not label:
            return None
        lowered = label.casefold()
        query = (
            "MATCH (c:Concept) "
            "WHERE toLower(c.name) = $name "
            "   OR toLower(coalesce(c.id,'')) = $name "
            "RETURN c.id AS id "
            "ORDER BY c.updated_at DESC NULLS LAST "
            "LIMIT 1"
        )
        try:
            result = self.db._run(query, {"name": lowered})
        except Exception:
            return None

        concept_id = None
        try:
            for record in result:
                concept_id = record.get("id")
                if concept_id:
                    break
        finally:
            try:
                result.close()
            except Exception:
                pass

        if concept_id:
            return self._find_concept_node_by_id(concept_id)
        return None

    def _relationship_exists(self, start_id: str, end_id: str, rel_type: str) -> bool:
        try:
            rels = self.db.find_relationships(
                start_node=start_id,
                end_node=end_id,
                rel_type=rel_type,
            )
        except Exception:
            return False
        return bool(rels)
