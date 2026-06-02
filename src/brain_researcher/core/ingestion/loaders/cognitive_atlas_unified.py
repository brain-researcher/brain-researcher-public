"""
Unified Cognitive Atlas Data Loader

This module provides a unified interface for loading Cognitive Atlas data,
preferring the pre-cleaned NICLIP version with fallback to API.

The NICLIP clean data includes:
- Concept hierarchies with process categories (ctp_C1-C8)
- Concept-to-task mappings
- Concept-to-process mappings
- Reduced task lists with top concepts
- Extended metadata and definitions

Author: Brain Researcher Team
"""

import copy
import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import numpy as np
import yaml

from brain_researcher.core.ingestion.utils.label_embedder import (
    HybridLabelEmbedder,
)

logger = logging.getLogger(__name__)


class CognitiveAtlasUnifiedLoader:
    """
    Unified loader for Cognitive Atlas data.

    Prefers NICLIP clean data (local JSON files) with fallback to API.
    """

    def __init__(
        self,
        use_niclip_data: bool = True,
        niclip_path: Optional[str] = None,
        data_dir: Optional[str] = None,
        use_ca_assertions: bool = True,
        ca_dump_path: Optional[str] = None,
    ):
        """
        Initialize the unified Cognitive Atlas loader.

        Args:
            use_niclip_data: Whether to use NICLIP clean data (recommended)
            niclip_path: Path to NICLIP data directory (auto-detected if None)
            data_dir: Output directory for storing fetched data
            use_ca_assertions: Whether to merge official Cognitive Atlas assertions
            ca_dump_path: Optional override for the Cognitive Atlas dump location
        """
        self.use_niclip = use_niclip_data
        self.use_ca_assertions = use_ca_assertions

        # Set paths
        if niclip_path:
            self.niclip_path = Path(niclip_path)
        else:
            # Try common locations relative to the repository/workspace
            search_paths = [
                Path("data/niclip/data/cognitive_atlas"),
                Path("data/niclip/cognitive_atlas"),
                Path("/data/niclip/data/cognitive_atlas"),
            ]
            for candidate in search_paths:
                expanded = candidate.expanduser()
                if expanded.exists():
                    self.niclip_path = expanded
                    break
            else:
                self.niclip_path = search_paths[0]

        data_root = ca_dump_path or data_dir
        self.data_dir = Path(data_root) if data_root else Path("data/cognitive_atlas")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cao_constructs_path = self.data_dir / "cao_constructs.json"
        self._cao_concept_process_path = self.data_dir / "cao_concept_to_process.json"

        self._cache_dir = self.data_dir / ".cache"
        self._ca_cache_file = self._cache_dir / "ca_assertions.json"
        if self.use_ca_assertions:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache for loaded data
        self._concepts_cache = None
        self._tasks_cache = None
        self._mappings_cache = None
        self._concept_detail_cache: Optional[Dict[str, Any]] = None
        self._task_detail_cache: Optional[Dict[str, Any]] = None
        self._cao_construct_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._ca_assertions_cache: Optional[
            Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Dict[str, Any]]]
        ] = None

        # Statistics
        niclip_available = self.use_niclip and self.niclip_path.exists()
        initial_source = (
            "niclip"
            if niclip_available
            else (
                "cognitive_atlas_cao" if self._cao_constructs_path.exists() else "api"
            )
        )
        self.stats = {
            "concepts_loaded": 0,
            "tasks_loaded": 0,
            "mappings_loaded": 0,
            "source": initial_source,
            "concept_source": initial_source,
            "task_source": None,
        }

        logger.info(
            f"Initialized CognitiveAtlasUnifiedLoader (source: {self.stats['source']})"
        )

        # Synonym resources for enhanced linking
        self._package_root = Path(__file__).resolve().parents[3]
        # TODO: migrate mapping files from configs/legacy/mappings to configs/br-kg
        self._mappings_dir = self._package_root / "configs" / "legacy" / "mappings"
        self._task_synonym_to_id, self._task_synonym_to_name = (
            self._load_task_synonyms()
        )
        self._concept_synonym_to_name = self._load_concept_synonyms()

    def load_concepts(self) -> List[Dict[str, Any]]:
        """
        Load cognitive concepts.

        Returns:
            List of concept dictionaries with id, name, definition, etc.
        """
        if self._concepts_cache is not None:
            return self._concepts_cache

        concept_source = "api"
        if self.use_niclip and self.niclip_path.exists():
            concepts = self._load_niclip_concepts()
            concept_source = "niclip"
        else:
            concepts = self._load_cao_concepts()
            if concepts:
                concept_source = "cognitive_atlas_cao"
            else:
                concepts = self._load_api_concepts()
                concept_source = "api"

        concepts = self._augment_concepts_with_cao_dump(concepts)

        self._concepts_cache = concepts
        self.stats["concepts_loaded"] = len(concepts)
        self.stats["source"] = concept_source
        self.stats["concept_source"] = concept_source
        logger.info(f"Loaded {len(concepts)} concepts from {concept_source}")

        return concepts

    def load_tasks(self) -> List[Dict[str, Any]]:
        """
        Load cognitive tasks.

        Returns:
            List of task dictionaries with id, name, definition, etc.
        """
        if self._tasks_cache is not None:
            return self._tasks_cache

        task_source = "api"
        if self.use_niclip and self.niclip_path.exists():
            tasks = self._load_niclip_tasks()
            task_source = "niclip"
        else:
            tasks = self._load_api_tasks()
            task_source = "api"

        self._tasks_cache = tasks
        self.stats["tasks_loaded"] = len(tasks)
        self.stats["source"] = task_source
        self.stats["task_source"] = task_source
        logger.info(f"Loaded {len(tasks)} tasks from {task_source}")

        return tasks

    def load_mappings(self) -> Dict[str, Any]:
        """
        Load concept-task-process mappings.

        Note: Mappings are only available from NICLIP clean data.

        Returns:
            Dictionary with mapping types as keys:
            - concept_to_task: Dict mapping concept IDs to task IDs
            - concept_to_process: Dict mapping concept names to process categories
            - task_to_concepts: Dict mapping task names to top 3 concepts
        """
        if self._mappings_cache is not None:
            return self._mappings_cache

        mappings = {
            "concept_to_task": {},
            "concept_to_process": {},
            "task_to_concepts": {},
        }

        if self.use_niclip and self.niclip_path.exists():
            # Load concept-to-task mapping
            concept_task_path = self.niclip_path / "concept_to_task.json"
            if concept_task_path.exists():
                with open(concept_task_path) as f:
                    mappings["concept_to_task"] = json.load(f)
                    logger.info(
                        f"Loaded {len(mappings['concept_to_task'])} concept-task mappings"
                    )

            # Load concept-to-process mapping
            concept_process_path = self.niclip_path / "concept_to_process.json"
            if concept_process_path.exists():
                with open(concept_process_path) as f:
                    mappings["concept_to_process"] = json.load(f)
                    logger.info(
                        f"Loaded {len(mappings['concept_to_process'])} concept-process mappings"
                    )

            auto_links = {}
            # Load reduced tasks (task to top concepts) and derive concept-task links
            reduced_tasks_path = self.niclip_path / "reduced_tasks.csv"
            if reduced_tasks_path.exists():
                import pandas as pd

                df = pd.read_csv(reduced_tasks_path)
                for _, row in df.iterrows():
                    task_name = row["task"]
                    concepts = [row["concept_1"], row["concept_2"], row["concept_3"]]
                    mappings["task_to_concepts"][task_name] = concepts
                logger.info(
                    f"Loaded {len(mappings['task_to_concepts'])} task-concept mappings"
                )
                auto_links = self._derive_concept_task_links(df)
            else:
                logger.warning(
                    "Reduced tasks file missing; skipping auto concept-task linking"
                )

            if auto_links:
                logger.info(
                    "Derived %d concept-task links via synonym expansion",
                    sum(len(v) for v in auto_links.values()),
                )
                self._merge_concept_task_links(mappings["concept_to_task"], auto_links)
        ca_map, ca_task_to_concepts, ca_metadata = self._load_ca_assertions()
        if ca_map:
            self._merge_concept_task_links(mappings["concept_to_task"], ca_map)
            ca_pairs = sum(len(v) for v in ca_map.values())
            logger.info(
                "Loaded %d concept-task assertions from Cognitive Atlas dumps",
                ca_pairs,
            )
        if ca_task_to_concepts:
            for task_id, concepts in ca_task_to_concepts.items():
                existing = mappings["task_to_concepts"].setdefault(task_id, [])
                merged = sorted({*existing, *concepts})
                mappings["task_to_concepts"][task_id] = merged
        if ca_metadata:
            mappings["task_concept_metadata"] = ca_metadata

        process_map = self._build_concept_process_map()
        if process_map:
            mappings["concept_to_process"] = process_map

        # Normalize concept->task mapping to ensure list output
        mappings["concept_to_task"] = self._normalize_concept_task_mapping(
            mappings["concept_to_task"]
        )

        self._mappings_cache = mappings
        self.stats["mappings_loaded"] = sum(len(m) for m in mappings.values())

        return mappings

    def _build_concept_process_map(self) -> Dict[str, List[Dict[str, Any]]]:
        """Construct mapping from concept IDs to their cognitive processes."""

        concepts = self.load_concepts() or []
        process_map: Dict[str, List[Dict[str, Any]]] = {}

        for concept in concepts:
            concept_id = concept.get("id")
            if not concept_id:
                continue
            class_entries = concept.get("concept_classes") or []
            if not class_entries:
                continue

            normalized: list[Dict[str, Any]] = []
            seen: set[str] = set()
            for raw in class_entries:
                if not isinstance(raw, dict):
                    continue
                class_id = raw.get("id") or raw.get("concept_class_id")
                name = raw.get("name") or raw.get("concept_class_name")
                if not class_id and name:
                    class_id = f"class:{self._sanitize_id_segment(name)}"
                if not class_id:
                    continue
                key = str(class_id)
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(
                    {
                        "id": key,
                        "name": name,
                        "relationship": raw.get("relationship", "CLASSIFIED_UNDER"),
                        "description": raw.get("description"),
                    }
                )

            if normalized:
                process_map[concept_id] = normalized

        return process_map

    # ------------------------------------------------------------------ #
    # Local detail loaders
    # ------------------------------------------------------------------ #

    def _load_full_concept_details(self) -> Dict[str, Any]:
        """Load full concept metadata from data/cognitive_atlas/concepts_full."""
        if self._concept_detail_cache is not None:
            return self._concept_detail_cache

        details: Dict[str, Any] = {}
        detail_dir = self.data_dir / "concepts_full"
        if not detail_dir.exists():
            self._concept_detail_cache = details
            return details

        for path in detail_dir.glob("*.json"):
            try:
                with path.open() as handle:
                    payload = json.load(handle)
                concept_id = payload.get("id")
                if concept_id:
                    details[concept_id] = payload
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Failed to load concept detail {path}: {exc}")

        self._concept_detail_cache = details
        return details

    def _load_full_task_details(self) -> Dict[str, Any]:
        """Load full task metadata from data/cognitive_atlas/tasks_full."""
        if self._task_detail_cache is not None:
            return self._task_detail_cache

        details: Dict[str, Any] = {}
        detail_dir = self.data_dir / "tasks_full"
        if not detail_dir.exists():
            self._task_detail_cache = details
            return details

        for path in detail_dir.glob("*.json"):
            try:
                with path.open() as handle:
                    payload = json.load(handle)
                task_id = payload.get("id")
                if task_id:
                    details[task_id] = payload
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Failed to load task detail {path}: {exc}")

        self._task_detail_cache = details
        return details

    def _load_ca_assertions(
        self,
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Dict[str, Any]]]:
        """Load Cognitive Atlas task->concept assertions from local dumps."""

        if not self.use_ca_assertions:
            return {}, {}, {}

        if self._ca_assertions_cache is not None:
            return self._ca_assertions_cache

        tasks_dir = self.data_dir / "tasks_full"
        if not tasks_dir.exists():
            logger.warning(
                "Cognitive Atlas tasks_full directory missing at %s; assertions disabled",
                tasks_dir,
            )
            self._ca_assertions_cache = ({}, {}, {})
            return self._ca_assertions_cache

        task_files = sorted(tasks_dir.glob("*.json"))
        if not task_files:
            logger.warning(
                "Cognitive Atlas tasks_full directory %s is empty", tasks_dir
            )
            self._ca_assertions_cache = ({}, {}, {})
            return self._ca_assertions_cache

        fingerprint = self._compute_ca_assertions_fingerprint(task_files)
        cached = self._load_cached_ca_assertions(fingerprint)
        if cached:
            logger.debug(
                "Loaded %d cached Cognitive Atlas assertions from %s",
                sum(len(v) for v in cached[0].values()),
                self._ca_cache_file,
            )
            self._ca_assertions_cache = cached
            return cached

        concept_to_task: Dict[str, Set[str]] = defaultdict(set)
        task_to_concepts: Dict[str, Set[str]] = defaultdict(set)
        edge_metadata: Dict[str, Dict[str, Any]] = {}
        assertion_count = 0

        for json_path in task_files:
            try:
                payload = json.loads(json_path.read_text())
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Failed to parse %s: %s", json_path, exc)
                continue

            task_id = payload.get("id")
            if not task_id:
                continue

            concepts_block = payload.get("concepts") or []
            if isinstance(concepts_block, dict):
                concepts_block = concepts_block.get("items", [])
            if not isinstance(concepts_block, list):
                logger.debug(
                    "Skipping malformed concepts payload for task %s in %s",
                    task_id,
                    json_path,
                )
                continue

            for concept in concepts_block:
                if not isinstance(concept, dict):
                    continue
                concept_id = concept.get("concept_id") or concept.get("id")
                if not concept_id:
                    continue

                concept_to_task[concept_id].add(task_id)
                if concept.get("name"):
                    task_to_concepts[task_id].add(concept["name"])

                key = f"{task_id}::{concept_id}"
                metadata = {
                    "method": "assertion",
                    "relationship": concept.get("relationship", "ASSERTS"),
                    "source": "cognitive_atlas",
                }
                contrasts = concept.get("contrasts") or []
                if contrasts:
                    metadata["contrasts"] = [
                        item.get("id") or item.get("name")
                        for item in contrasts
                        if isinstance(item, dict)
                    ]
                edge_metadata[key] = metadata
                assertion_count += 1

        logger.info(
            "Parsed %d Cognitive Atlas assertions from %s",
            assertion_count,
            tasks_dir,
        )
        self._persist_ca_assertions_cache(
            fingerprint, concept_to_task, task_to_concepts, edge_metadata
        )
        self._ca_assertions_cache = (concept_to_task, task_to_concepts, edge_metadata)
        return self._ca_assertions_cache

    # ------------------------------------------------------------------ #
    # Cognitive Atlas assertion caching helpers
    # ------------------------------------------------------------------ #

    def _compute_ca_assertions_fingerprint(self, files: Iterable[Path]) -> str:
        hasher = hashlib.sha1()
        count = 0
        for path in files:
            count += 1
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            hasher.update(path.name.encode("utf-8"))
            hasher.update(str(int(stat.st_mtime_ns)).encode("utf-8"))
            hasher.update(str(stat.st_size).encode("utf-8"))
        hasher.update(str(count).encode("utf-8"))
        return hasher.hexdigest()

    def _load_cached_ca_assertions(
        self, fingerprint: str
    ) -> Optional[
        Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, Dict[str, Any]]]
    ]:
        cache_file = getattr(self, "_ca_cache_file", None)
        if not cache_file or not cache_file.exists():
            return None
        try:
            payload = json.loads(cache_file.read_text())
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to read cached Cognitive Atlas assertions: %s", exc)
            return None

        if payload.get("fingerprint") != fingerprint:
            return None

        concept_map = self._deserialize_set_map(payload.get("concept_to_task", {}))
        task_map = self._deserialize_set_map(payload.get("task_to_concepts", {}))
        metadata = payload.get("edge_metadata") or {}
        return concept_map, task_map, metadata

    def _persist_ca_assertions_cache(
        self,
        fingerprint: str,
        concept_to_task: Dict[str, Set[str]],
        task_to_concepts: Dict[str, Set[str]],
        edge_metadata: Dict[str, Dict[str, Any]],
    ) -> None:
        if not self.use_ca_assertions or not getattr(self, "_ca_cache_file", None):
            return

        payload = {
            "fingerprint": fingerprint,
            "concept_to_task": self._serialize_set_map(concept_to_task),
            "task_to_concepts": self._serialize_set_map(task_to_concepts),
            "edge_metadata": edge_metadata,
        }
        try:
            tmp_path = self._ca_cache_file.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, sort_keys=True))
            tmp_path.replace(self._ca_cache_file)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Failed to persist Cognitive Atlas cache to %s: %s",
                self._ca_cache_file,
                exc,
            )

    @staticmethod
    def _serialize_set_map(mapping: Dict[str, Set[str]]) -> Dict[str, List[str]]:
        return {key: sorted(value) for key, value in mapping.items()}

    @staticmethod
    def _deserialize_set_map(
        raw: Dict[str, Iterable[str]] | None,
    ) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}
        for key, values in (raw or {}).items():
            if values is None:
                result[key] = set()
            else:
                result[key] = {str(item) for item in values if item is not None}
        return result

    @staticmethod
    def _merge_concept_relationships(
        *relationship_lists: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Combine multiple relationship lists into one, removing obvious duplicates."""
        merged: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for rel_list in relationship_lists:
            if not rel_list:
                continue
            for entry in rel_list:
                if not isinstance(entry, dict):
                    continue
                target_id = entry.get("id") or entry.get("concept_id")
                relationship = entry.get("relationship")
                key = (target_id or "", relationship or "")
                if key in seen:
                    continue
                seen.add(key)
                merged.append(copy.deepcopy(entry))

        return merged

    # ------------------------------------------------------------------ #
    # Synonym-aware mapping helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_ca_id(raw_id: Optional[str]) -> Optional[str]:
        if not raw_id:
            return None
        candidate = raw_id.strip()
        if not candidate:
            return None
        if ":" in candidate:
            candidate = candidate.split(":", 1)[1]
        return candidate.lower()

    @staticmethod
    def _sanitize_id_segment(raw: Optional[str]) -> str:
        if not raw:
            return ""
        segment = raw.strip().lower()
        for ch in " :/\\|":
            segment = segment.replace(ch, "-")
        return segment.strip("-")

    def _load_task_synonyms(self) -> tuple[Dict[str, str], Dict[str, str]]:
        """Load task synonym mappings (synonym -> canonical id/name)."""
        mapping_path = self._mappings_dir / "task_synonyms.yaml"
        id_map: Dict[str, str] = {}
        name_map: Dict[str, str] = {}

        if not mapping_path.exists():
            return id_map, name_map

        try:
            entries = yaml.safe_load(mapping_path.read_text()) or []
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(f"Failed to load task synonyms: {exc}")
            return id_map, name_map

        if not isinstance(entries, list):
            return id_map, name_map

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            canonical = (entry.get("canonical") or "").strip()
            ca_id_norm = self._normalize_ca_id(entry.get("cognitive_atlas_id"))
            synonyms = entry.get("synonyms") or []

            targets = []
            if canonical:
                targets.append(canonical.lower())
            for syn in synonyms:
                if isinstance(syn, str) and syn.strip():
                    targets.append(syn.strip().lower())

            if ca_id_norm:
                for term in targets:
                    id_map.setdefault(term, ca_id_norm)
            elif canonical:
                for term in targets:
                    name_map.setdefault(term, canonical)

        return id_map, name_map

    def _load_concept_synonyms(self) -> Dict[str, str]:
        """Load concept synonym mappings (synonym -> canonical name or id)."""
        mapping_path = self._mappings_dir / "concept_synonyms.yaml"
        name_map: Dict[str, str] = {}

        if not mapping_path.exists():
            return name_map

        try:
            entries = yaml.safe_load(mapping_path.read_text()) or []
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Failed to load concept synonyms: {exc}")
            return name_map

        if not isinstance(entries, list):
            return name_map

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            canonical = (entry.get("canonical") or "").strip()
            if not canonical:
                continue

            terms = [canonical.lower()]
            for syn in entry.get("synonyms") or []:
                if isinstance(syn, str) and syn.strip():
                    terms.append(syn.strip().lower())

            source_aliases = entry.get("source_aliases") or {}
            if isinstance(source_aliases, dict):
                for alias_list in source_aliases.values():
                    if isinstance(alias_list, list):
                        for alias in alias_list:
                            if isinstance(alias, str) and alias.strip():
                                terms.append(alias.strip().lower())

            # Some entries include cognitive atlas ids instead of names.
            ca_id = entry.get("cognitive_atlas_id")
            if isinstance(ca_id, str) and ca_id.strip():
                terms.append(ca_id.strip().lower())

            for term in terms:
                name_map.setdefault(term, canonical)

        return name_map

    @staticmethod
    def _split_aliases(value: str) -> List[str]:
        if not value or not isinstance(value, str):
            return []
        separators = [",", ";", "|", "/"]
        tokens = [value]
        for sep in separators:
            new_tokens: List[str] = []
            for token in tokens:
                new_tokens.extend(token.split(sep))
            tokens = new_tokens
        return [token.strip() for token in tokens if token and token.strip()]

    def _resolve_task_id(
        self,
        label: str,
        name_lookup: Dict[str, str],
        id_lookup: Dict[str, str],
    ) -> Optional[str]:
        key = label.strip().lower()
        if not key:
            return None
        if key in name_lookup:
            return name_lookup[key]

        syn_id = self._task_synonym_to_id.get(key)
        if syn_id and syn_id in id_lookup:
            return id_lookup[syn_id]

        syn_name = self._task_synonym_to_name.get(key)
        if syn_name:
            return name_lookup.get(syn_name.lower())

        # Handle values that might already be IDs
        norm_id = self._normalize_ca_id(label)
        if norm_id and norm_id in id_lookup:
            return id_lookup[norm_id]

        return None

    def _resolve_concept_id(
        self,
        label: str,
        name_lookup: Dict[str, str],
        id_lookup: Dict[str, str],
    ) -> Optional[str]:
        key = label.strip().lower()
        if not key:
            return None
        if key in name_lookup:
            return name_lookup[key]

        syn_name = self._concept_synonym_to_name.get(key)
        if syn_name:
            candidate = name_lookup.get(syn_name.lower())
            if candidate:
                return candidate
            norm_id = self._normalize_ca_id(syn_name)
            if norm_id and norm_id in id_lookup:
                return id_lookup[norm_id]

        norm_id = self._normalize_ca_id(label)
        if norm_id and norm_id in id_lookup:
            return id_lookup[norm_id]

        return None

    def _derive_concept_task_links(self, task_df=None) -> Dict[str, set[str]]:
        """Derive concept-to-task links using synonyms and reduced task mappings."""
        reduced_tasks_path = self.niclip_path / "reduced_tasks.csv"
        if task_df is None:
            if not reduced_tasks_path.exists():
                return {}
            import pandas as pd

            task_df = pd.read_csv(reduced_tasks_path)

        if task_df.empty:
            return {}

        concepts = self.load_concepts()
        tasks = self.load_tasks()

        task_id_lookup = {
            task.get("id", "").lower(): task.get("id")
            for task in tasks
            if task.get("id")
        }
        task_name_lookup: Dict[str, str] = {}
        for task in tasks:
            tid = task.get("id")
            if not tid:
                continue
            name = (task.get("name") or "").strip()
            if name:
                task_name_lookup.setdefault(name.lower(), tid)
            alias = task.get("alias")
            for token in self._split_aliases(alias or ""):
                task_name_lookup.setdefault(token.lower(), tid)

        for term, norm_id in self._task_synonym_to_id.items():
            if norm_id in task_id_lookup:
                task_name_lookup.setdefault(term, task_id_lookup[norm_id])
        for term, canonical in self._task_synonym_to_name.items():
            if canonical:
                resolved = task_name_lookup.get(canonical.lower())
                if resolved:
                    task_name_lookup.setdefault(term, resolved)

        concept_id_lookup = {
            concept.get("id", "").lower(): concept.get("id")
            for concept in concepts
            if concept.get("id")
        }
        concept_name_lookup: Dict[str, str] = {}
        for concept in concepts:
            cid = concept.get("id")
            if not cid:
                continue
            name = (concept.get("name") or "").strip()
            if name:
                concept_name_lookup.setdefault(name.lower(), cid)
            alias = concept.get("alias")
            for token in self._split_aliases(alias or ""):
                concept_name_lookup.setdefault(token.lower(), cid)

        links: Dict[str, set[str]] = defaultdict(set)
        concept_columns = [
            col for col in task_df.columns if str(col).lower().startswith("concept")
        ]

        for _, row in task_df.iterrows():
            task_name = str(row.get("task", "")).strip()
            if not task_name:
                continue
            task_id = self._resolve_task_id(task_name, task_name_lookup, task_id_lookup)
            if not task_id:
                continue

            for col in concept_columns:
                concept_name = str(row.get(col, "")).strip()
                if not concept_name or concept_name.lower() == "nan":
                    continue
                concept_id = self._resolve_concept_id(
                    concept_name, concept_name_lookup, concept_id_lookup
                )
                if not concept_id:
                    continue
                links[concept_id].add(task_id)

        # Expand links using embedding similarity for remaining tasks
        embedding_added = 0
        try:
            embedder = HybridLabelEmbedder()
            task_labels = [str(task.get("name", "") or "") for task in tasks]
            concept_labels = [
                str(concept.get("name", "") or "") for concept in concepts
            ]
            batch = embedder.compute_embeddings(task_labels, concept_labels)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(f"Embedding-based concept-task linking failed: {exc}")
        else:
            if batch:
                emb_a = batch.emb_a
                emb_b = batch.emb_b
                mask_a = batch.mask_a
                mask_b = batch.mask_b

                if mask_b and not all(mask_b):
                    emb_b = emb_b.copy()
                    for idx, ok in enumerate(mask_b):
                        if not ok:
                            emb_b[idx] = 0.0

                similarity = emb_a @ emb_b.T
                top_n = 3
                threshold = 0.75

                for task_idx, task in enumerate(tasks):
                    if mask_a and not mask_a[task_idx]:
                        continue
                    task_id = task.get("id")
                    if not task_id:
                        continue
                    scores = similarity[task_idx]
                    if scores is None or not len(scores):
                        continue
                    top_indices = np.argsort(scores)[-top_n:]
                    for concept_idx in sorted(
                        top_indices, key=lambda idx: scores[idx], reverse=True
                    ):
                        score = float(scores[concept_idx])
                        if score < threshold:
                            continue
                        concept_id = concepts[concept_idx].get("id")
                        if not concept_id:
                            continue
                        before = len(links[concept_id])
                        links[concept_id].add(task_id)
                        if len(links[concept_id]) > before:
                            embedding_added += 1
                logger.info(
                    "Added %d concept-task links via embedding similarity (model=%s)",
                    embedding_added,
                    batch.model_label,
                )
            else:
                logger.warning(
                    "HybridLabelEmbedder returned no embeddings; skipping embedding expansion"
                )

        # Fuzzy matching fallback for environments without embedding backends
        try:
            from rapidfuzz import fuzz, process

            label_to_concept: Dict[str, str] = {}
            for concept in concepts:
                cid = concept.get("id")
                if not cid:
                    continue
                name = (concept.get("name") or "").strip()
                if name:
                    label_to_concept.setdefault(name.lower(), cid)
                for alias in self._split_aliases(concept.get("alias", "")):
                    label_to_concept.setdefault(alias.lower(), cid)

            for term, canonical in self._concept_synonym_to_name.items():
                canonical_id = concept_name_lookup.get(canonical.lower())
                if canonical_id:
                    label_to_concept.setdefault(term.lower(), canonical_id)

            choices = list(label_to_concept.keys())
            fuzzy_added = 0

            min_fuzzy_score = 60
            if choices:
                for task in tasks:
                    task_id = task.get("id")
                    if not task_id:
                        continue
                    candidate_labels = [task.get("name", "")]
                    candidate_labels.extend(self._split_aliases(task.get("alias", "")))

                    for candidate in candidate_labels:
                        candidate = (candidate or "").strip()
                        if not candidate:
                            continue
                        matches = process.extract(
                            candidate,
                            choices,
                            scorer=fuzz.token_sort_ratio,
                            limit=10,
                        )
                        for match_label, score, _ in matches:
                            if score < min_fuzzy_score:
                                continue
                            concept_id = label_to_concept.get(match_label)
                            if not concept_id:
                                continue
                            before = len(links[concept_id])
                            links[concept_id].add(task_id)
                            if len(links[concept_id]) > before:
                                fuzzy_added += 1
            logger.info("Added %d concept-task links via fuzzy matching", fuzzy_added)
        except Exception as exc:  # pragma: no cover - rapidfuzz optional
            logger.warning(f"Fuzzy concept-task linking failed: {exc}")

        return links

    def _merge_concept_task_links(
        self,
        base_mapping: Dict[str, Any],
        auto_links: Dict[str, set[str]],
    ) -> None:
        for concept_id, task_ids in auto_links.items():
            if not concept_id or not task_ids:
                continue
            existing = base_mapping.get(concept_id)
            existing_set: set[str] = set()
            if isinstance(existing, str):
                existing_set.add(existing)
            elif isinstance(existing, (list, tuple, set)):
                existing_set.update(
                    str(item) for item in existing if isinstance(item, str)
                )
            elif existing:
                existing_set.add(str(existing))
            existing_set.update(task_ids)
            base_mapping[concept_id] = sorted(existing_set)

    @staticmethod
    def _normalize_concept_task_mapping(
        mapping: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        normalized: Dict[str, List[str]] = {}
        for concept_id, value in mapping.items():
            if not value:
                continue
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, (list, tuple, set)):
                values = [item for item in value if isinstance(item, str)]
            else:
                values = [str(value)]

            dedup = sorted({val for val in values if val and val.strip()})
            if dedup:
                normalized[concept_id] = dedup
        return normalized

    def _load_niclip_concepts(self) -> List[Dict[str, Any]]:
        """Load concepts from NICLIP clean JSON files."""
        concepts = []

        # Try extended version first (has more metadata)
        extended_path = self.niclip_path / "concept_extended_snapshot-02-19-25.json"
        basic_path = self.niclip_path / "concept_snapshot-02-19-25.json"

        concept_file = extended_path if extended_path.exists() else basic_path

        concept_details = self._load_full_concept_details()

        if concept_file.exists():
            with open(concept_file) as f:
                raw_concepts = json.load(f)

                for concept in raw_concepts:
                    concept_id = concept.get("id")
                    detail = concept_details.get(concept_id, {})
                    definition_text = detail.get(
                        "definition_text", concept.get("definition_text", "")
                    )
                    alias_raw = detail.get("alias", concept.get("alias", ""))
                    normalized = {
                        "id": concept_id,
                        "name": concept.get("name"),
                        "definition": definition_text,
                        "alias": alias_raw,
                        "aliases": self._split_aliases(alias_raw),
                        "concept_class": concept.get("id_concept_class", ""),
                        "source": "cognitive_atlas_niclip",
                        "creation_time": detail.get(
                            "creation_time", concept.get("creation_time")
                        ),
                        "last_updated": detail.get(
                            "last_updated", concept.get("last_updated")
                        ),
                        "metadata": {
                            "def_id": detail.get("def_id", concept.get("def_id")),
                            "def_id_user": detail.get(
                                "def_id_user", concept.get("def_id_user")
                            ),
                            "event_stamp": detail.get(
                                "event_stamp", concept.get("event_stamp")
                            ),
                        },
                        "concept_classes": copy.deepcopy(
                            detail.get("conceptclasses", [])
                        ),
                        "related_concepts": self._merge_concept_relationships(
                            detail.get("concepts", []),
                            detail.get("relationships", []),
                        ),
                        "contrast_links": copy.deepcopy(detail.get("contrasts", [])),
                        "citations": copy.deepcopy(detail.get("citations", [])),
                    }
                    concepts.append(normalized)
        else:
            logger.warning(f"NICLIP concept file not found at {concept_file}")
            # Fall back to API
            return self._load_api_concepts()

        return concepts

    def _load_niclip_tasks(self) -> List[Dict[str, Any]]:
        """Load tasks from NICLIP clean JSON files."""
        tasks = []

        task_file = self.niclip_path / "task_snapshot-02-19-25.json"
        task_details = self._load_full_task_details()

        if task_file.exists():
            with open(task_file) as f:
                raw_tasks = json.load(f)

                for task in raw_tasks:
                    task_id = task.get("id")
                    detail = task_details.get(task_id, {})
                    definition_text = detail.get(
                        "definition_text", task.get("definition_text", "")
                    )
                    alias_raw = detail.get("alias", task.get("alias", ""))
                    normalized = {
                        "id": task_id,
                        "name": task.get("name"),
                        "definition": definition_text,
                        "alias": alias_raw,
                        "aliases": self._split_aliases(alias_raw),
                        "source": "cognitive_atlas_niclip",
                        "creation_time": detail.get(
                            "creation_time", task.get("creation_time")
                        ),
                        "last_updated": detail.get(
                            "last_updated", task.get("last_updated")
                        ),
                        "metadata": {
                            "def_id": detail.get("def_id", task.get("def_id")),
                            "def_id_user": detail.get(
                                "def_id_user", task.get("def_id_user")
                            ),
                            "event_stamp": detail.get(
                                "event_stamp", task.get("event_stamp")
                            ),
                        },
                        "concept_relations": copy.deepcopy(detail.get("concepts", [])),
                        "conditions": copy.deepcopy(detail.get("conditions", [])),
                        "indicators": copy.deepcopy(detail.get("indicators", [])),
                        "citations": copy.deepcopy(detail.get("citation", [])),
                        "contrasts": copy.deepcopy(detail.get("contrasts", [])),
                        "batteries": copy.deepcopy(detail.get("batteries", [])),
                        "disorders": copy.deepcopy(detail.get("disorders", [])),
                        "external_datasets": copy.deepcopy(
                            detail.get("external_datasets", [])
                        ),
                        "implementations": copy.deepcopy(
                            detail.get("implementations", [])
                        ),
                    }
                    tasks.append(normalized)
        else:
            logger.warning(f"NICLIP task file not found at {task_file}")
            # Fall back to API
            return self._load_api_tasks()

        return tasks

    def _load_api_concepts(self) -> List[Dict[str, Any]]:
        """Load concepts from Cognitive Atlas API (fallback)."""
        try:
            from cognitiveatlas.api import get_concept

            logger.info("Fetching concepts from Cognitive Atlas API...")
            result = get_concept()
            concepts_df = result.pandas

            concepts = []
            for _, row in concepts_df.iterrows():
                concept = {
                    "id": str(row.get("id", "")),
                    "name": str(row.get("name", "")).strip(),
                    "definition": str(row.get("definition", "")).strip(),
                    "alias": str(row.get("alias", "")).strip(),
                    "concept_class": str(row.get("id_concept_class", "")),
                    "source": "cognitive_atlas_api",
                    "creation_time": row.get("creation_time"),
                    "last_updated": datetime.now().isoformat(),
                }

                if concept["name"]:
                    concepts.append(concept)

            return concepts

        except (ImportError, Exception) as e:
            logger.error(f"Failed to load concepts from API: {e}")
            # Return sample data as last resort
            return self._create_sample_concepts()

    def _load_cao_concepts(self) -> List[Dict[str, Any]]:
        """Load constructs produced from the CAO OWL dump (if available)."""

        records = self._load_cao_construct_records()
        if not records:
            return []
        return [copy.deepcopy(payload) for payload in records.values()]

    def _augment_concepts_with_cao_dump(
        self, concepts: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Merge CAO construct metadata/links into the provided concept list."""

        records = self._load_cao_construct_records()
        if not records:
            return concepts or []

        concepts = concepts or []
        by_id: Dict[str, Dict[str, Any]] = {}
        for concept in concepts:
            cid = self._normalize_concept_id(concept.get("id"))
            if cid:
                by_id[cid] = concept

        for cid, payload in records.items():
            if cid in by_id:
                concept = by_id[cid]
                merged_classes = self._merge_concept_class_entries(
                    concept.get("concept_classes") or [],
                    payload.get("concept_classes") or [],
                )
                if merged_classes:
                    concept["concept_classes"] = merged_classes
                if payload.get("definition") and not concept.get("definition"):
                    concept["definition"] = payload["definition"]
                if payload.get("name") and not concept.get("name"):
                    concept["name"] = payload["name"]
                if payload.get("label") and not concept.get("label"):
                    concept["label"] = payload["label"]
                existing_synonyms = set(concept.get("synonyms") or [])
                existing_synonyms.update(payload.get("synonyms") or [])
                if existing_synonyms:
                    concept["synonyms"] = sorted(existing_synonyms)
            else:
                concepts.append(copy.deepcopy(payload))

        return concepts

    def _load_cao_construct_records(self) -> Dict[str, Dict[str, Any]]:
        """Read CAO construct metadata + process links from disk."""

        if self._cao_construct_cache is not None:
            return self._cao_construct_cache

        self._ensure_cao_artifacts_generated()

        if not self._cao_constructs_path.exists():
            self._cao_construct_cache = {}
            return self._cao_construct_cache

        try:
            constructs = json.loads(self._cao_constructs_path.read_text())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to parse CAO constructs dump %s: %s",
                self._cao_constructs_path,
                exc,
            )
            constructs = []

        process_rows: List[Dict[str, Any]] = []
        if self._cao_concept_process_path.exists():
            try:
                process_rows = json.loads(self._cao_concept_process_path.read_text())
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to parse CAO concept→process dump %s: %s",
                    self._cao_concept_process_path,
                    exc,
                )

        process_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in process_rows:
            cid = self._normalize_concept_id(row.get("concept_id"))
            pid = row.get("process_id")
            if not cid or not pid:
                continue
            process_map[cid].append(
                {
                    "id": pid,
                    "name": row.get("process_name") or pid,
                    "relationship": "CLASSIFIED_UNDER",
                    "source": "cognitive_atlas",
                }
            )

        normalized: Dict[str, Dict[str, Any]] = {}
        for payload in constructs:
            cid = self._normalize_concept_id(payload.get("id"))
            if not cid:
                continue
            normalized[cid] = {
                "id": cid,
                "name": payload.get("label") or payload.get("name") or cid,
                "label": payload.get("label") or payload.get("name") or cid,
                "definition": payload.get("definition"),
                "synonyms": payload.get("synonyms") or [],
                "source": "cognitive_atlas_cao",
                "concept_classes": copy.deepcopy(process_map.get(cid, [])),
            }

        self._cao_construct_cache = normalized
        if normalized:
            logger.info(
                "Loaded %d CAO constructs from %s",
                len(normalized),
                self._cao_constructs_path,
            )
        return self._cao_construct_cache

    @staticmethod
    def _normalize_concept_id(value: Optional[str]) -> str:
        if not value:
            return ""
        return str(value).strip().lower()

    def _merge_concept_class_entries(
        self,
        existing: List[Dict[str, Any]],
        additions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for entry in existing + additions:
            if not isinstance(entry, dict):
                continue
            class_id = entry.get("id") or entry.get("concept_class_id")
            if not class_id:
                continue
            key = str(class_id)
            if key in seen:
                continue
            seen.add(key)
            normalized = copy.deepcopy(entry)
            normalized["id"] = key
            if not normalized.get("name"):
                normalized["name"] = (
                    entry.get("concept_class_name") or entry.get("process_name") or key
                )
            normalized.setdefault("relationship", "CLASSIFIED_UNDER")
            normalized.setdefault("source", entry.get("source", "cognitive_atlas"))
            merged.append(normalized)
        return merged

    def _ensure_cao_artifacts_generated(self) -> None:
        """Generate CAO construct artifacts from OWL when JSON dumps are missing or stale."""

        owl_path = self.data_dir / "cogat.owl"
        if not owl_path.exists():
            return

        needs_constructs = not self._cao_constructs_path.exists()
        needs_links = not self._cao_concept_process_path.exists()

        if not needs_constructs and not needs_links:
            try:
                owl_mtime = owl_path.stat().st_mtime
                if (
                    self._cao_constructs_path.exists()
                    and self._cao_constructs_path.stat().st_mtime < owl_mtime
                ):
                    needs_constructs = True
                if (
                    self._cao_concept_process_path.exists()
                    and self._cao_concept_process_path.stat().st_mtime < owl_mtime
                ):
                    needs_links = True
            except OSError:  # pragma: no cover - defensive
                return

        if not needs_constructs and not needs_links:
            return

        try:
            tree = ET.parse(str(owl_path))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to parse CAO OWL dump %s: %s", owl_path, exc)
            return

        root = tree.getroot()
        ns = {
            "owl": "http://www.w3.org/2002/07/owl#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "dc": "http://purl.org/dc/elements/1.1/",
            "skos": "http://www.w3.org/2004/02/skos/core#",
        }

        process_labels: Dict[str, str] = {}
        constructs: List[Dict[str, Any]] = []
        links: List[Dict[str, Any]] = []

        def text(el: Optional[ET.Element]) -> str:
            if el is None or el.text is None:
                return ""
            return el.text.strip()

        def coalesce(*values: str) -> str:
            for value in values:
                if value:
                    return value
            return ""

        def fragment(iri: Optional[str]) -> str:
            if not iri:
                return ""
            if "#" in iri:
                return iri.split("#", 1)[1]
            return iri.rsplit("/", 1)[-1]

        for cls in root.findall("owl:Class", ns):
            about = cls.get(f"{{{ns['rdf']}}}about")
            if not about:
                continue

            fragment_id = fragment(about)
            label = coalesce(
                text(cls.find("rdfs:label", ns)),
                text(cls.find("skos:prefLabel", ns)),
                text(cls.find("dc:Title", ns)),
            )

            if fragment_id.startswith("ctp_"):
                process_label = label or text(cls.find("skos:prefLabel", ns))
                if process_label:
                    process_labels[fragment_id] = process_label
                continue

            identifier = text(cls.find("dc:identifier", ns)) or fragment_id
            if not identifier:
                continue

            identifier_lower = identifier.lower()
            if not identifier_lower.startswith(("cao_", "trm_")):
                continue

            definition = coalesce(
                text(cls.find("skos:definition", ns)),
                text(cls.find("rdfs:comment", ns)),
                text(cls.find("dc:description", ns)),
            )

            synonyms = set()
            for tag in ("skos:prefLabel", "skos:altLabel", "dc:Title", "rdfs:label"):
                for syn in cls.findall(tag, ns):
                    value = text(syn)
                    if value:
                        synonyms.add(value)
            if label:
                synonyms.discard(label)

            constructs.append(
                {
                    "id": identifier,
                    "label": label or identifier,
                    "definition": definition,
                    "synonyms": sorted(synonyms),
                }
            )

            for top in cls.findall("skos:hasTopConcept", ns):
                process_iri = top.get(f"{{{ns['rdf']}}}resource")
                pid = fragment(process_iri)
                if pid:
                    links.append({"concept_id": identifier, "process_id": pid})

        if needs_constructs:
            try:
                self._cao_constructs_path.write_text(
                    json.dumps(constructs, indent=2, ensure_ascii=False)
                )
                logger.info(
                    "Generated %d CAO constructs from %s", len(constructs), owl_path
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to write CAO constructs dump %s: %s",
                    self._cao_constructs_path,
                    exc,
                )

        if needs_links:
            for row in links:
                pid = row["process_id"]
                row["process_name"] = process_labels.get(pid, pid)
            try:
                self._cao_concept_process_path.write_text(
                    json.dumps(links, indent=2, ensure_ascii=False)
                )
                logger.info(
                    "Generated %d CAO concept→process rows from %s",
                    len(links),
                    owl_path,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to write CAO concept→process dump %s: %s",
                    self._cao_concept_process_path,
                    exc,
                )

    def _load_api_tasks(self) -> List[Dict[str, Any]]:
        """Load tasks from Cognitive Atlas API (fallback)."""
        try:
            from cognitiveatlas.api import get_task

            logger.info("Fetching tasks from Cognitive Atlas API...")
            result = get_task()
            tasks_df = result.pandas

            tasks = []
            for _, row in tasks_df.iterrows():
                task = {
                    "id": str(row.get("id", "")),
                    "name": str(row.get("name", "")).strip(),
                    "definition": str(row.get("definition", "")).strip(),
                    "alias": str(row.get("alias", "")).strip(),
                    "source": "cognitive_atlas_api",
                    "creation_time": row.get("creation_time"),
                    "last_updated": datetime.now().isoformat(),
                }

                if task["name"]:
                    tasks.append(task)

            return tasks

        except (ImportError, Exception) as e:
            logger.error(f"Failed to load tasks from API: {e}")
            # Return sample data as last resort
            return self._create_sample_tasks()

    def _create_sample_concepts(self) -> List[Dict[str, Any]]:
        """Create sample concept data as last resort."""
        return [
            {
                "id": "trm_4a3fd79d0a1a8",
                "name": "working memory",
                "definition": "System for temporarily holding and manipulating information",
                "concept_class": "ctp_C1",
                "source": "sample",
            },
            {
                "id": "trm_4a3fd79d0d070",
                "name": "attention",
                "definition": "Selective concentration on relevant information",
                "concept_class": "ctp_C2",
                "source": "sample",
            },
        ]

    def _create_sample_tasks(self) -> List[Dict[str, Any]]:
        """Create sample task data as last resort."""
        return [
            {
                "id": "trm_4aae62e4ad209",
                "name": "n-back task",
                "definition": "Continuous performance task measuring working memory",
                "source": "sample",
            },
            {
                "id": "trm_4aae62e4ae6df",
                "name": "Stroop task",
                "definition": "Task measuring selective attention and cognitive flexibility",
                "source": "sample",
            },
        ]

    def get_concept_hierarchy(self) -> Dict[str, List[str]]:
        """
        Get concept hierarchy based on concept classes.

        Returns:
            Dictionary mapping concept class IDs to lists of concept names
        """
        concepts = self.load_concepts()
        hierarchy = {}

        for concept in concepts:
            class_id = concept.get("concept_class", "unknown")
            if class_id not in hierarchy:
                hierarchy[class_id] = []
            hierarchy[class_id].append(concept["name"])

        return hierarchy

    def get_process_categories(self) -> Dict[str, str]:
        """
        Get process category descriptions.

        Returns:
            Dictionary mapping process IDs (ctp_C1-C8) to descriptions
        """
        # Based on NICLIP categorization
        return {
            "ctp_C1": "Memory and Learning",
            "ctp_C2": "Attention and Executive",
            "ctp_C3": "Reasoning and Problem Solving",
            "ctp_C4": "Perception and Sensory",
            "ctp_C5": "Motor and Action",
            "ctp_C6": "Language and Communication",
            "ctp_C7": "Motivation and Reward",
            "ctp_C8": "Emotion and Social",
        }

    def save_to_database(self, db_path: str) -> None:
        """
        Save loaded data to a database.

        Args:
            db_path: Path to database file
        """
        # This would integrate with BRKGGraphDB
        # Implementation depends on database schema
        pass

    def export_to_json(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        Export all loaded data to JSON files.

        Args:
            output_dir: Directory to save files (uses self.data_dir if None)

        Returns:
            Dictionary mapping data types to file paths
        """
        output_dir = Path(output_dir) if output_dir else self.data_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        files = {}

        # Export concepts
        concepts = self.load_concepts()
        concepts_file = output_dir / "concepts.json"
        with open(concepts_file, "w") as f:
            json.dump(concepts, f, indent=2)
        files["concepts"] = str(concepts_file)

        # Export tasks
        tasks = self.load_tasks()
        tasks_file = output_dir / "tasks.json"
        with open(tasks_file, "w") as f:
            json.dump(tasks, f, indent=2)
        files["tasks"] = str(tasks_file)

        # Export mappings
        mappings = self.load_mappings()
        mappings_file = output_dir / "mappings.json"
        with open(mappings_file, "w") as f:
            json.dump(mappings, f, indent=2)
        files["mappings"] = str(mappings_file)

        logger.info(f"Exported data to {output_dir}")
        return files

    def get_statistics(self) -> Dict[str, Any]:
        """Get loader statistics."""
        return self.stats.copy()


# Convenience functions for backward compatibility
def load_cognitive_atlas(use_niclip=True, **kwargs):
    """
    Load Cognitive Atlas data using the unified loader.

    Args:
        use_niclip: Whether to use NICLIP clean data (recommended)
        **kwargs: Additional arguments for the loader

    Returns:
        Tuple of (concepts, tasks, mappings)
    """
    loader = CognitiveAtlasUnifiedLoader(use_niclip_data=use_niclip, **kwargs)
    concepts = loader.load_concepts()
    tasks = loader.load_tasks()
    mappings = loader.load_mappings()
    return concepts, tasks, mappings


if __name__ == "__main__":
    # Example usage
    loader = CognitiveAtlasUnifiedLoader(use_niclip_data=True)

    # Load data
    concepts = loader.load_concepts()
    tasks = loader.load_tasks()
    mappings = loader.load_mappings()

    # Print statistics
    print(f"Loaded {len(concepts)} concepts")
    print(f"Loaded {len(tasks)} tasks")
    print(f"Concept-task mappings: {len(mappings['concept_to_task'])}")
    print(f"Concept-process mappings: {len(mappings['concept_to_process'])}")
    print(f"Task-concept mappings: {len(mappings['task_to_concepts'])}")

    # Show hierarchy
    hierarchy = loader.get_concept_hierarchy()
    for class_id, concept_names in list(hierarchy.items())[:3]:
        print(f"\n{class_id}: {concept_names[:5]}...")
