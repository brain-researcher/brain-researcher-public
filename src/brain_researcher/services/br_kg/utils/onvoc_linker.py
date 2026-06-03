"""Utilities for linking entities to ONVOC classes."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.config.mapping_resolver import resolve_mapping_path
from brain_researcher.config.paths import resolve_from_config
from brain_researcher.semantics.taxonomy.matcher import normalize_text
from brain_researcher.services.br_kg.utils.onvoc_tree import OnvocTree, OnvocTreeError

try:  # pragma: no cover - rapidfuzz optional
    from rapidfuzz import fuzz, process  # type: ignore
except ImportError:  # pragma: no cover
    fuzz = None
    process = None

logger = logging.getLogger(__name__)


ONVOC_NODE_LABELS = ["ONVOC", "OnvocClass", "Concept", "OntologyConcept"]


DEFAULT_CROSSWALK_PATH = (
    Path(__file__).resolve().parent.parent / "mappings" / "onvoc_crosswalk.yaml"
)
CANONICAL_CROSSWALK_PATH = resolve_mapping_path(
    "onvoc_crosswalk",
    fallback=DEFAULT_CROSSWALK_PATH,
    must_exist=False,
)
DEFAULT_TREE_PATH = resolve_mapping_path(
    "onvoc_tree",
    fallback=resolve_from_config("onvoc_tree.yaml"),
    must_exist=False,
)


class OnvocLinker:
    """Helper that assigns ONVOC classes based on crosswalks and heuristics."""

    def __init__(
        self,
        db,
        *,
        crosswalk_path: Path | None = None,
        tree_path: Path | None = None,
    ) -> None:
        self.db = db
        resolved_crosswalk = resolve_mapping_path(
            "onvoc_crosswalk",
            requested_path=crosswalk_path,
            fallback=DEFAULT_CROSSWALK_PATH,
            must_exist=False,
        )
        resolved_tree = resolve_mapping_path(
            "onvoc_tree",
            requested_path=tree_path,
            fallback=DEFAULT_TREE_PATH,
            must_exist=False,
        )
        self.crosswalk = self._load_crosswalk(
            resolved_crosswalk or CANONICAL_CROSSWALK_PATH
        )
        self._onvoc_by_id: dict[str, dict[str, Any]] = {}
        self._normalized_name_index: dict[str, set[str]] = {}
        self._fuzzy_lookup: dict[str, str] = {}
        self._fuzzy_strings: list[str] = []
        self._tree = self._load_tree(resolved_tree or DEFAULT_TREE_PATH)
        self._cannot_link_map: dict[str, set[str]] = (
            self._tree.cannot_link if self._tree else {}
        )
        self.available = self._load_onvoc_classes()

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------
    def _load_crosswalk(self, path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {
                "tasks": {},
                "concepts": {},
                "contrasts": {},
                "datasets": {},
                "statsmaps": {},
            }
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return {
            "tasks": payload.get("tasks", {}),
            "concepts": payload.get("concepts", {}),
            "contrasts": payload.get("contrasts", {}),
            "datasets": payload.get("datasets", {}),
            "statsmaps": payload.get("statsmaps", {}),
        }

    def _load_tree(self, path: Path) -> OnvocTree | None:
        if not path.exists():
            return None
        try:
            return OnvocTree.load(path)
        except OnvocTreeError as exc:
            logger.warning("Unable to load ONVOC tree from %s: %s", path, exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Unexpected error while loading ONVOC tree %s: %s", path, exc
            )
        return None

    def _load_onvoc_classes(self) -> bool:
        try:
            result = self.db._run(
                """
                MATCH (o)
                WHERE any(lbl IN labels(o) WHERE lbl IN $onvoc_labels)
                  AND (coalesce(o.scheme, '') = 'ONVOC' OR o.id STARTS WITH 'ONVOC_')
                RETURN o.id AS id,
                       coalesce(o.name, o.label, o.id) AS name,
                       coalesce(o.synonyms, o.alt_labels, o.aliases, []) AS alt_labels
                """,
                {"onvoc_labels": ONVOC_NODE_LABELS},
            )
        except Exception as exc:  # pragma: no cover - driver errors
            logger.warning("Unable to load ONVOC classes: %s", exc)
            return False

        classes = list(result)
        try:
            result.close()
        except Exception:  # pragma: no cover - best effort
            pass

        if not classes:
            logger.warning("ONVOC classes not present in graph; skipping ONVOC tagging")
            return False

        for record in classes:
            class_id = record.get("id")
            name = record.get("name")
            if not class_id or not name:
                continue
            alt_labels = record.get("alt_labels") or []
            self._onvoc_by_id[class_id] = {
                "name": name,
                "alt_labels": alt_labels,
            }
            for label in [name, *alt_labels]:
                normalized = normalize_text(str(label))
                if not normalized:
                    continue
                self._normalized_name_index.setdefault(normalized, set()).add(class_id)
                self._register_fuzzy_term(label, class_id)
        return True

    def _register_fuzzy_term(self, label: str, class_id: str) -> None:
        if not label:
            return
        if label not in self._fuzzy_lookup:
            self._fuzzy_strings.append(label)
        self._fuzzy_lookup[label] = class_id

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def link_task_analysis(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        canonical_ids: Sequence[str],
        concept_ids: Sequence[str],
    ) -> int:
        hints = {
            "canonical_ids": list(canonical_ids),
            "concept_ids": list(concept_ids),
        }
        return self._link_entity(
            entity_id,
            entity_type="tasks",
            names=names,
            hints=hints,
        )

    def link_contrast(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        canonical_ids: Sequence[str],
        concept_ids: Sequence[str],
    ) -> int:
        hints = {
            "canonical_ids": list(canonical_ids),
            "concept_ids": list(concept_ids),
        }
        return self._link_entity(
            entity_id,
            entity_type="contrasts",
            names=names,
            hints=hints,
        )

    def link_stats_map(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        contrast_onvoc_ids: Sequence[str],
        task_onvoc_ids: Sequence[str],
        dataset_ids: Sequence[str],
    ) -> int:
        hints = {
            "related_onvoc": list({*contrast_onvoc_ids, *task_onvoc_ids}),
            "dataset_ids": list(dataset_ids),
        }
        return self._link_entity(
            entity_id,
            entity_type="statsmaps",
            names=names,
            hints=hints,
        )

    def link_dataset(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        dataset_ids: Sequence[str],
    ) -> int:
        hints = {"canonical_ids": list(dataset_ids)}
        return self._link_entity(
            entity_id,
            entity_type="datasets",
            names=names,
            hints=hints,
        )

    # ------------------------------------------------------------------
    # Core linking logic
    # ------------------------------------------------------------------
    def _link_entity(
        self,
        entity_id: str,
        *,
        entity_type: str,
        names: Sequence[str],
        hints: dict[str, Sequence[str]] | None = None,
    ) -> int:
        if not self.available:
            return 0

        candidates: dict[str, dict[str, Any]] = {}
        hints = hints or {}

        # 1) Direct crosswalk via canonical identifiers
        for canonical_id in hints.get("canonical_ids", []):
            canonical_id = str(canonical_id)
            crosswalk = self._lookup_crosswalk(entity_type, canonical_id)
            if not crosswalk:
                continue
            self._register_candidate(
                candidates,
                crosswalk.get("primary"),
                base_confidence=1.0,
                method="crosswalk",
                evidence={"canonical_id": canonical_id},
            )
            for label in crosswalk.get("labels", []) or []:
                matched = self._match_by_label(label)
                self._register_candidate(
                    candidates,
                    matched,
                    base_confidence=0.95,
                    method="crosswalk_label",
                    evidence={"label": label},
                )

        # 2) Propagate from related ONVOC ids (e.g., contrast -> concept)
        for related in hints.get("related_onvoc", []) or []:
            self._register_candidate(
                candidates,
                related,
                base_confidence=0.82,
                method="propagated",
                evidence={"related_onvoc": related},
            )

        # 3) Dataset crosswalks
        for dataset_id in hints.get("dataset_ids", []) or []:
            crosswalk = self._lookup_crosswalk("datasets", dataset_id)
            if crosswalk:
                self._register_candidate(
                    candidates,
                    crosswalk.get("primary"),
                    base_confidence=0.9,
                    method="dataset_crosswalk",
                    evidence={"dataset_id": dataset_id},
                )

        # 4) Name-based exact matching
        for name in names:
            normalized = normalize_text(str(name))
            if not normalized:
                continue
            for class_id in self._normalized_name_index.get(normalized, []):
                self._register_candidate(
                    candidates,
                    class_id,
                    base_confidence=0.9,
                    method="name_match",
                    evidence={"name": name},
                )

        # 5) Fuzzy matching
        if process and self._fuzzy_strings:
            query = normalize_text(" ".join(names))
            if query:
                try:
                    results = process.extract(
                        query,
                        self._fuzzy_strings,
                        scorer=fuzz.QRatio if fuzz else None,
                        limit=5,
                    )
                except Exception:  # pragma: no cover - rapidfuzz optional
                    results = []
                for match_string, score, _ in results:
                    if score < 75:
                        continue
                    class_id = self._fuzzy_lookup.get(match_string)
                    confidence = 0.85 * (score / 100)
                    self._register_candidate(
                        candidates,
                        class_id,
                        base_confidence=confidence,
                        method="fuzzy",
                        evidence={"match": match_string, "score": score},
                    )

        created = 0
        selected: set[str] = set()
        if self._cannot_link_map:
            selected.update(self._existing_onvoc_ids(entity_id))
        for class_id, payload in sorted(
            candidates.items(), key=lambda item: -item[1]["confidence"]
        ):
            if not class_id or class_id not in self._onvoc_by_id:
                continue
            if (
                selected
                and self._tree
                and self._tree.conflicts_with(class_id, selected)
            ):
                logger.debug(
                    "Skipping ONVOC class %s due to cannot-link constraint", class_id
                )
                continue
            delta = self._upsert_relationship(
                entity_id,
                class_id,
                method=payload["method"],
                confidence=payload["confidence"],
                evidence=payload.get("evidence"),
            )
            if delta:
                selected.add(class_id)
            created += delta

        if created:
            self._update_primary_onvoc(entity_id)
        return created

    # ------------------------------------------------------------------
    # Candidate registration helpers
    # ------------------------------------------------------------------
    def _lookup_crosswalk(self, section: str, key: str) -> dict[str, Any] | None:
        section_map = self.crosswalk.get(section, {})
        return section_map.get(key)

    def _match_by_label(self, label: str) -> str | None:
        if not label:
            return None
        normalized = normalize_text(str(label))
        if not normalized:
            return None
        ids = self._normalized_name_index.get(normalized)
        if ids:
            # Return deterministic ordering
            return sorted(ids)[0]
        return None

    def _register_candidate(
        self,
        candidates: dict[str, dict[str, Any]],
        class_id: str | None,
        *,
        base_confidence: float,
        method: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        if not class_id:
            return
        existing = candidates.get(class_id)
        if existing and existing["confidence"] >= base_confidence:
            return
        candidates[class_id] = {
            "confidence": base_confidence,
            "method": method,
            "evidence": evidence or {},
        }

    # ------------------------------------------------------------------
    # Relationship helpers
    # ------------------------------------------------------------------
    def _upsert_relationship(
        self,
        entity_id: str,
        class_id: str,
        *,
        method: str,
        confidence: float,
        evidence: dict[str, Any] | None = None,
    ) -> int:
        existing_conf = self._get_existing_link_confidence(entity_id, class_id)
        if existing_conf is not None and existing_conf >= confidence:
            return 0

        props = {
            "source": "onvoc_linker",
            "method": method,
            "confidence": float(confidence),
        }
        if evidence:
            props["evidence_json"] = json.dumps(evidence, sort_keys=True)

        self.db.create_relationship(entity_id, class_id, "IN_ONVOC", props)
        return 1

    def _get_existing_link_confidence(
        self, entity_id: str, class_id: str
    ) -> float | None:
        try:
            result = self.db._run(
                """
                MATCH (n {id:$entity_id})-[r:IN_ONVOC]->(o {id:$class_id})
                WHERE any(lbl IN labels(o) WHERE lbl IN $onvoc_labels)
                  AND (coalesce(o.scheme, '') = 'ONVOC' OR o.id STARTS WITH 'ONVOC_')
                RETURN r.confidence AS confidence
                """,
                {
                    "entity_id": entity_id,
                    "class_id": class_id,
                    "onvoc_labels": ONVOC_NODE_LABELS,
                },
            )
        except Exception:
            return None
        record = result.single()
        try:
            result.close()
        except Exception:
            pass
        if not record:
            return None
        return record.get("confidence")

    def _existing_onvoc_ids(self, entity_id: str) -> set[str]:
        query = """
        MATCH (n {id:$entity_id})-[r:IN_ONVOC]->(o)
        WHERE any(lbl IN labels(o) WHERE lbl IN $onvoc_labels)
          AND (coalesce(o.scheme, '') = 'ONVOC' OR o.id STARTS WITH 'ONVOC_')
        RETURN o.id AS id
        """
        try:
            result = self.db._run(
                query,
                {"entity_id": entity_id, "onvoc_labels": ONVOC_NODE_LABELS},
            )
        except Exception:
            return set()
        ids = {record.get("id") for record in result if record.get("id")}
        try:
            result.close()
        except Exception:
            pass
        return {id_ for id_ in ids if id_}

    def _update_primary_onvoc(self, entity_id: str) -> None:
        query = """
        MATCH (n {id:$entity_id})-[r:IN_ONVOC]->(o)
        WHERE any(lbl IN labels(o) WHERE lbl IN $onvoc_labels)
          AND (coalesce(o.scheme, '') = 'ONVOC' OR o.id STARTS WITH 'ONVOC_')
        RETURN o.id AS id, r.confidence AS confidence
        """
        try:
            result = self.db._run(
                query,
                {"entity_id": entity_id, "onvoc_labels": ONVOC_NODE_LABELS},
            )
        except Exception:
            return
        records = list(result)
        try:
            result.close()
        except Exception:
            pass
        if not records:
            return
        best = max(records, key=lambda rec: rec.get("confidence", 0.0))
        best_id = best.get("id")
        best_conf = best.get("confidence")
        if not best_id:
            return
        try:
            self.db._run(
                "MATCH (n {id:$entity_id}) SET n.primary_onvoc_id = $class_id, "
                "n.primary_onvoc_confidence = $confidence",
                {"entity_id": entity_id, "class_id": best_id, "confidence": best_conf},
            )
        except Exception:
            pass
