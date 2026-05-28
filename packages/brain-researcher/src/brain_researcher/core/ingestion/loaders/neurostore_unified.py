"""Unified loader for Neurostore study metadata and task annotations."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Set, Tuple, Union

import yaml

from brain_researcher.semantics.taxonomy.matcher import (
    TaskMatcher as TaxonomyTaskMatcher,
)
from brain_researcher.semantics.taxonomy.matcher import (
    normalize_text as taxonomy_normalize,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"[\u2010-\u2015-]+")


@dataclass
class TaskMatchResult:
    """Structural task-match result used by the core Neurostore loader."""

    match: Dict[str, Any]
    method: str
    fallback_node_id: Optional[str] = None


class TaskTaxonomyResolverProtocol(Protocol):
    """Resolver surface accepted from service code."""

    matcher: Any

    def match_label(self, label: str) -> Optional[TaskMatchResult]: ...


def _normalize_text(value: Optional[str]) -> str:
    """Lowercase, ASCII-fold, and collapse whitespace."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.lower()
    text = _DASH_RE.sub("-", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip(" -")


def _ensure_str_list(value: Any) -> List[str]:
    """Return a clean list of strings."""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        iterable = value
    else:
        iterable = [value]
    result: List[str] = []
    for item in iterable:
        if item is None:
            continue
        if isinstance(item, str):
            candidate = item.strip()
        else:
            candidate = str(item).strip()
        if candidate:
            result.append(candidate)
    return result


def _coerce_str(value: Any) -> str:
    """Convert value to a trimmed string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _unique(seq: Iterable[str]) -> List[str]:
    """Return list with order-preserving uniqueness."""
    seen: set[str] = set()
    unique_values: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            unique_values.append(item)
    return unique_values


_DOI_URL_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)


def _normalize_doi_value(value: Any) -> Optional[str]:
    """Normalize DOI strings by trimming prefixes and punctuation."""
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    candidate = _DOI_URL_PREFIX.sub("", candidate)
    if candidate.lower().startswith("doi:"):
        candidate = candidate[4:].lstrip()
    candidate = candidate.strip().rstrip(".,;")
    if not candidate:
        return None
    return candidate.lower()


def _add_doi_candidate(dois: Set[str], candidate: Any) -> None:
    """Recursively add DOI candidates from nested structures."""
    if candidate is None:
        return
    if isinstance(candidate, dict):
        for value in candidate.values():
            _add_doi_candidate(dois, value)
        return
    if isinstance(candidate, (list, tuple, set)):
        for value in candidate:
            _add_doi_candidate(dois, value)
        return
    normalized = _normalize_doi_value(candidate)
    if normalized:
        dois.add(normalized)


def collect_dois_from_record(record: Dict[str, Any]) -> Set[str]:
    """Return normalized DOI strings from a Neurostore publication record."""
    dois: Set[str] = set()
    if not isinstance(record, dict):
        return dois

    _add_doi_candidate(dois, record.get("doi"))

    identifiers = record.get("identifiers")
    if isinstance(identifiers, dict):
        for key, value in identifiers.items():
            if "doi" in key.lower():
                _add_doi_candidate(dois, value)

    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        _add_doi_candidate(dois, metadata.get("doi"))
        for key in ("dois", "alternate_dois"):
            _add_doi_candidate(dois, metadata.get(key))
        meta_identifiers = metadata.get("identifiers")
        if isinstance(meta_identifiers, dict):
            for key, value in meta_identifiers.items():
                if "doi" in key.lower():
                    _add_doi_candidate(dois, value)

    for extra_key in (
        "dois",
        "alternate_dois",
        "alternateDois",
        "alternate_ids",
        "alternateIds",
    ):
        _add_doi_candidate(dois, record.get(extra_key))

    links = record.get("links")
    if isinstance(links, dict):
        for key, value in links.items():
            if "doi" in key.lower():
                _add_doi_candidate(dois, value)

    citations = record.get("citations")
    if isinstance(citations, (list, tuple, set)):
        for citation in citations:
            if isinstance(citation, dict):
                _add_doi_candidate(dois, citation.get("doi"))

    return dois


class NeurostoreUnifiedLoader:
    """Unified loader for Neurostore JSON exports."""

    _family_crosswalk_cache: Optional[Dict[str, Dict[str, Any]]] = None
    _slug_family_cache: Optional[Dict[str, str]] = None

    def __init__(
        self,
        data_dir: Optional[Union[str, Path]] = None,
        include_invalid: bool = False,
        alias_map_path: Optional[Union[str, Path]] = None,
        alias_map: Optional[Dict[str, str]] = None,
        task_resolver: Optional[TaskTaxonomyResolverProtocol] = None,
    ):
        self.repo_root = self._find_repo_root()
        self.data_dir = self._resolve_data_dir(data_dir)
        self.include_invalid = include_invalid
        self.alias_map = self._prepare_alias_map(alias_map, alias_map_path)
        self.task_resolver = task_resolver
        if task_resolver:
            self._taxonomy_matcher = getattr(task_resolver, "matcher", None)
        else:
            try:
                self._taxonomy_matcher = TaxonomyTaskMatcher()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug(
                    "TaskMatcher initialization failed for Neurostore loader taxonomy matching: %s",
                    exc,
                )
                self._taxonomy_matcher = None
        self._ensure_family_crosswalk()
        self.family_definitions = self.__class__._family_crosswalk_cache or {}
        self.slug_family_lookup = self.__class__._slug_family_cache or {}
        self.ingested_at = datetime.utcnow().isoformat()

        self.studies: List[Dict[str, Any]] = []
        self.tasks: List[Dict[str, Any]] = []
        self.study_payloads: Dict[str, Dict[str, Any]] = {}
        self.skipped_invalid: List[str] = []
        self.errors: List[str] = []

    def _find_repo_root(self) -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "pyproject.toml").exists():
                return parent
        return current.parents[4]

    def _resolve_data_dir(self, data_dir: Optional[Union[str, Path]]) -> Path:
        if data_dir:
            return Path(data_dir).expanduser()
        env_dir = os.environ.get("NEUROSTORE_DATA_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        return self.repo_root / "data" / "neurostore"

    def _prepare_alias_map(
        self,
        alias_map: Optional[Dict[str, str]],
        alias_map_path: Optional[Union[str, Path]],
    ) -> Dict[str, str]:
        data: Optional[Dict[str, Any]] = alias_map

        if data is None:
            if alias_map_path:
                candidate = Path(alias_map_path)
            else:
                candidate = (
                    self.repo_root
                    / "scripts"
                    / "neurostore_task"
                    / "taxonomy"
                    / "alias_map.json"
                )
            if candidate.exists():
                try:
                    with candidate.open("r", encoding="utf-8") as handle:
                        data = json.load(handle)
                except Exception as exc:
                    logger.warning(
                        "Failed to load Neurostore alias map from %s: %s",
                        candidate,
                        exc,
                    )
                    data = None

        normalized: Dict[str, str] = {}
        if data:
            for raw_key, raw_value in data.items():
                key = _normalize_text(str(raw_key))
                value = _normalize_text(str(raw_value))
                if key:
                    normalized[key] = value
        return normalized

    @staticmethod
    def _slugify_label(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        slug = _SLUG_RE.sub("-", value.lower()).strip("-")
        return slug or None

    @staticmethod
    def _family_label(family_id: str) -> str:
        label = family_id
        if label.startswith("tf_"):
            label = label[3:]
        return label.replace("_", " ").title()

    @staticmethod
    def _collection_node_id(study_id: str) -> str:
        return f"neurostore_collection:{study_id}"

    @staticmethod
    def collect_dois(record: Dict[str, Any]) -> Set[str]:
        """Expose DOI extraction so upstream loaders can reuse the logic."""
        return collect_dois_from_record(record or {})

    def _derive_study_title(
        self,
        info: Dict[str, Any],
        results: Dict[str, Any],
        fallback: Optional[str] = None,
    ) -> Optional[str]:
        candidates = [
            info.get("title"),
            info.get("name"),
            info.get("study_title"),
            results.get("StudyTitle"),
            results.get("title"),
            results.get("Name"),
            fallback,
        ]
        for candidate in candidates:
            text = _coerce_str(candidate)
            if text:
                return text
        return None

    def _ensure_family_crosswalk(self) -> None:
        if self.__class__._family_crosswalk_cache is not None:
            return

        crosswalk_path = (
            self.repo_root
            / "configs"
            / "taxonomy"
            / "crosswalks"
            / "families__to__onvoc.v1.yaml"
        )
        if not crosswalk_path.exists():
            logger.debug("Family crosswalk not found at %s", crosswalk_path)
            self.__class__._family_crosswalk_cache = {}
            self.__class__._slug_family_cache = {}
            return

        try:
            data = yaml.safe_load(crosswalk_path.read_text()) or {}
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to parse %s: %s", crosswalk_path, exc)
            self.__class__._family_crosswalk_cache = {}
            self.__class__._slug_family_cache = {}
            return

        family_map: Dict[str, Dict[str, Any]] = {}
        slug_map: Dict[str, str] = {}
        for entry in data.get("mappings", []):
            family_id = entry.get("family_id")
            if not family_id:
                continue
            slugs = entry.get("seeds", {}).get("slugs", []) or []
            family_map[family_id] = {
                "family_id": family_id,
                "label": self._family_label(family_id),
                "onvoc_uri": entry.get("onvoc_uri"),
                "slugs": slugs,
            }
            for slug in slugs:
                slug_map[slug] = family_id

        self.__class__._family_crosswalk_cache = family_map
        self.__class__._slug_family_cache = slug_map

    def _resolve_family_from_labels(
        self,
        candidates: Iterable[Tuple[Optional[str], str]],
    ) -> Optional[Dict[str, Any]]:
        slug_map = self.slug_family_lookup
        family_map = self.family_definitions
        for label, source in candidates:
            slug = self._slugify_label(label)
            if not slug:
                continue
            family_id = slug_map.get(slug)
            if not family_id:
                continue
            meta = dict(family_map.get(family_id, {}))
            meta.setdefault("family_id", family_id)
            meta.setdefault("label", self._family_label(family_id))
            meta["slug"] = slug
            meta["source"] = source
            return meta
        return None

    def _infer_task_family(
        self,
        taxonomy_match: Optional[Dict[str, Any]],
        name_original: Optional[str],
        concepts: Iterable[str],
        domains: Iterable[str],
    ) -> Optional[Dict[str, Any]]:
        candidates: List[Tuple[Optional[str], str]] = []
        if taxonomy_match:
            candidates.append((taxonomy_match.get("label"), "taxonomy_label"))
            candidates.append((taxonomy_match.get("match_string"), "taxonomy_match"))
            canonical_id = taxonomy_match.get("canonical_id")
            if canonical_id:
                canonical_clean = (
                    canonical_id.split(":")[-1] if ":" in canonical_id else canonical_id
                )
                candidates.append((canonical_clean, "taxonomy_canonical_id"))
            entity = taxonomy_match.get("entity") or {}
            for alias in entity.get("alt_labels") or []:
                candidates.append((alias, "taxonomy_alias"))
            source_aliases = entity.get("source_aliases") or {}
            for alias_list in source_aliases.values():
                for alias in alias_list or []:
                    candidates.append((alias, "taxonomy_source_alias"))

        candidates.append((name_original, "task_name"))
        for concept in concepts:
            candidates.append((concept, "concept"))
        for domain in domains:
            candidates.append((domain, "domain"))

        return self._resolve_family_from_labels(candidates)

    def _load_json(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            logger.warning("Missing Neurostore file: %s", path)
            self.errors.append(f"missing:{path}")
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            self.errors.append(f"invalid:{path}")
            return None

    def _build_study_record(
        self,
        study_id: str,
        info: Dict[str, Any],
        results: Dict[str, Any],
        info_path: Path,
        results_path: Path,
    ) -> Dict[str, Any]:
        identifiers = info.get("identifiers") or {}
        clean_identifiers = {k: v for k, v in identifiers.items() if v}
        modalities = _unique(_ensure_str_list(results.get("Modality")))
        fmri_tasks = results.get("fMRITasks") or []
        behavioral_tasks = results.get("BehavioralTasks") or []

        study_objective = _coerce_str(results.get("StudyObjective")) or None
        exclude_reason = results.get("Exclude")
        collection_id = self._collection_node_id(study_id)
        title = self._derive_study_title(info, results, study_objective)

        record = {
            "study_id": study_id,
            "identifiers": clean_identifiers,
            "modalities": modalities,
            "study_objective": study_objective,
            "title": title,
            "exclude": exclude_reason,
            "valid": bool(info.get("valid", True)),
            "ingest_date": info.get("date"),
            "inputs": info.get("inputs") or {},
            "stats": {
                "fmri_tasks": len(fmri_tasks),
                "behavioral_tasks": len(behavioral_tasks),
            },
            "source": "neurostore",
            "paths": {"info": str(info_path), "results": str(results_path)},
            "collection_id": collection_id,
        }
        record["publication_id"] = self._resolve_publication_id(record)
        return record

    def load_studies(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if self.study_payloads and not refresh:
            return self.studies

        self.studies = []
        self.study_payloads = {}
        self.skipped_invalid = []

        if not self.data_dir.exists():
            logger.warning("Neurostore data directory not found: %s", self.data_dir)
            return []

        for results_path in sorted(self.data_dir.glob("*/results.json")):
            study_dir = results_path.parent
            study_id = study_dir.name
            info_path = study_dir / "info.json"

            results = self._load_json(results_path)
            if results is None:
                continue

            info = self._load_json(info_path) or {}
            valid = bool(info.get("valid", True))

            if not valid and not self.include_invalid:
                self.skipped_invalid.append(study_id)
                continue

            study_record = self._build_study_record(
                study_id, info, results, info_path, results_path
            )
            self.studies.append(study_record)
            self.study_payloads[study_id] = {
                "info": info,
                "results": results,
                "paths": {"info": info_path, "results": results_path},
            }

        return self.studies

    def _resolve_publication_id(self, study: Dict[str, Any]) -> str:
        identifiers = study.get("identifiers", {})
        if identifiers.get("pmid"):
            return f"pmid:{identifiers['pmid']}"
        if identifiers.get("doi"):
            return f"doi:{identifiers['doi']}"
        if identifiers.get("dbid"):
            return f"neurostore:{identifiers['dbid']}"
        return f"neurostore:{study['study_id']}"

    def _parse_resting_state(self, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = _coerce_str(value).lower()
        if not text:
            return None
        return text in {"true", "1", "yes", "y"}

    def _normalize_concepts(self, concepts: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for concept in concepts:
            candidate = _normalize_text(concept)
            if not candidate:
                continue
            mapped = self.alias_map.get(candidate, candidate)
            if mapped and mapped not in seen:
                seen.add(mapped)
                normalized.append(mapped)
        return normalized

    def _match_task_label(self, label: Optional[str]) -> Optional[TaskMatchResult]:
        if not label:
            return None
        cleaned = label.strip()
        if not cleaned:
            return None

        if self.task_resolver:
            return self.task_resolver.match_label(cleaned)

        match = self._local_taxonomy_match(cleaned)
        if match:
            match["match_method"] = "taxonomy_rule"
            return TaskMatchResult(match=match, method="taxonomy_rule")
        return None

    def _local_taxonomy_match(self, label: str) -> Optional[Dict[str, Any]]:
        if not self._taxonomy_matcher:
            return None

        match = self._taxonomy_matcher.match(label)
        if match:
            return match

        normalized = taxonomy_normalize(label)
        if normalized and normalized != label:
            match = self._taxonomy_matcher.match(normalized)
            if match:
                return match

        if "(" in label and ")" in label:
            for part in re.split(r"[()]", label):
                part = part.strip()
                if not part:
                    continue
                maybe = self._taxonomy_matcher.match(taxonomy_normalize(part))
                if maybe:
                    return maybe

        for token in re.split(r"[/,;\s]+", label):
            token = token.strip()
            if len(token) < 3:
                continue
            maybe = self._taxonomy_matcher.match(taxonomy_normalize(token))
            if maybe:
                return maybe
        return None

    def _build_task_texts(
        self,
        name: str,
        description: str,
        design_details: str,
        conditions: List[str],
        metrics: List[str],
        concepts: List[str],
    ) -> Tuple[str, str]:
        parts = [part for part in (name, description, design_details) if part]
        text_name_description = ". ".join(parts)

        extended_parts = list(parts)
        if conditions:
            extended_parts.append(f"conditions: {', '.join(conditions)}")
        if metrics:
            extended_parts.append(f"metrics: {', '.join(metrics)}")
        if concepts:
            extended_parts.append(f"concepts: {', '.join(concepts)}")

        text_with_concepts = ". ".join(extended_parts)
        return text_name_description, text_with_concepts

    def _build_task_record(
        self,
        study_id: str,
        task_type: str,
        task_index: int,
        task_data: Any,
        modalities: List[str],
        study_objective: Optional[str],
        publication_id: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(task_data, dict):
            logger.debug(
                "Skipping Neurostore %s task %s because payload is %s",
                task_type,
                task_index,
                type(task_data).__name__,
            )
            return None

        collection_id = self._collection_node_id(study_id)
        name_original = _coerce_str(task_data.get("TaskName")) or None
        description_original = _coerce_str(task_data.get("TaskDescription")) or None
        design_details_original = _coerce_str(task_data.get("DesignDetails")) or None
        task_duration = _coerce_str(task_data.get("TaskDuration")) or None

        design_list = _ensure_str_list(task_data.get("TaskDesign"))
        conditions_original = _ensure_str_list(task_data.get("Conditions"))
        metrics_original = _ensure_str_list(task_data.get("TaskMetrics"))
        concepts_original = _ensure_str_list(task_data.get("Concepts"))
        domains_original = _ensure_str_list(task_data.get("Domain"))

        taxonomy_match_payload: Optional[Dict[str, Any]] = None
        taxonomy_result = self._match_task_label(name_original)
        if not taxonomy_result and description_original:
            taxonomy_result = self._match_task_label(description_original)
        if taxonomy_result:
            taxonomy_match_payload = dict(taxonomy_result.match)
            if taxonomy_result.fallback_node_id:
                taxonomy_match_payload["_fallback_node_id"] = (
                    taxonomy_result.fallback_node_id
                )
            taxonomy_match_payload.setdefault("match_method", taxonomy_result.method)

        concepts_normalized = self._normalize_concepts(concepts_original)
        domains_normalized = [
            value
            for value in (_normalize_text(domain) for domain in domains_original)
            if value
        ]
        conditions_normalized = [
            value
            for value in (
                _normalize_text(condition) for condition in conditions_original
            )
            if value
        ]
        metrics_normalized = [
            value
            for value in (_normalize_text(metric) for metric in metrics_original)
            if value
        ]
        design_normalized = [
            value for value in (_normalize_text(item) for item in design_list) if value
        ]

        name_normalized = _normalize_text(name_original)
        description_normalized = _normalize_text(description_original)
        design_details_normalized = _normalize_text(design_details_original)

        text_name_description, text_with_concepts = self._build_task_texts(
            name_normalized,
            description_normalized,
            design_details_normalized,
            conditions_normalized,
            metrics_normalized,
            concepts_normalized,
        )
        family_meta = self._infer_task_family(
            taxonomy_match_payload,
            name_original,
            concepts_normalized,
            domains_normalized,
        )

        task_uid = f"{study_id}:{task_type}:{task_index}"
        resting_state_flag = (
            self._parse_resting_state(task_data.get("RestingState"))
            if task_type == "fmri"
            else None
        )
        resting_state_metadata = (
            task_data.get("RestingStateMetadata") if task_type == "fmri" else None
        )
        if resting_state_metadata and not isinstance(resting_state_metadata, dict):
            resting_state_metadata = None

        record = {
            "task_uid": task_uid,
            "study_id": study_id,
            "collection_id": collection_id,
            "task_type": task_type,
            "task_index": task_index,
            "publication_id": publication_id,
            "name_original": name_original,
            "name": name_normalized,
            "description_original": description_original,
            "description": description_normalized,
            "design_details_original": design_details_original,
            "design_details": design_details_normalized,
            "task_design": design_list,
            "design_normalized": design_normalized,
            "conditions_original": conditions_original,
            "conditions": _unique(conditions_normalized),
            "metrics_original": metrics_original,
            "metrics": _unique(metrics_normalized),
            "concepts_original": concepts_original,
            "concepts_normalized": concepts_normalized,
            "domains_original": domains_original,
            "domains_normalized": _unique(domains_normalized),
            "modality": modalities,
            "study_objective": study_objective,
            "resting_state": resting_state_flag,
            "resting_state_metadata": resting_state_metadata,
            "task_duration": task_duration,
            "source": "neurostore",
            "text_name_description": text_name_description,
            "text_with_concepts": text_with_concepts,
            "taxonomy_match": taxonomy_match_payload,
        }
        if taxonomy_match_payload:
            record["canonical_task_id"] = taxonomy_match_payload.get("canonical_id")
            record["canonical_task_label"] = taxonomy_match_payload.get("label")
            record["match_method"] = taxonomy_match_payload.get(
                "match_method"
            ) or taxonomy_match_payload.get("method")
            record["match_confidence"] = taxonomy_match_payload.get("confidence")
        if family_meta:
            record["family_id"] = family_meta.get("family_id")
            record["family_label"] = family_meta.get("label")
            record["family_slug"] = family_meta.get("slug")
            record["family_source"] = family_meta.get("source")
            record["family_onvoc_uri"] = family_meta.get("onvoc_uri")
        return record

    def extract_tasks(
        self,
        include_fmri: bool = True,
        include_behavioral: bool = True,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        if not self.studies or refresh:
            self.load_studies(refresh=refresh)

        if not self.study_payloads:
            return []

        if not self.tasks or refresh:
            self.tasks = []
            for study in self.studies:
                study_id = study["study_id"]
                payload = self.study_payloads.get(study_id)
                if not payload:
                    continue
                results = payload["results"]
                modalities = study.get("modalities", [])
                study_objective = study.get("study_objective")
                publication_id = self._resolve_publication_id(study)

                for idx, task_data in enumerate(results.get("fMRITasks") or []):
                    record = self._build_task_record(
                        study_id,
                        "fmri",
                        idx,
                        task_data,
                        modalities,
                        study_objective,
                        publication_id,
                    )
                    if record:
                        self.tasks.append(record)

                for idx, task_data in enumerate(results.get("BehavioralTasks") or []):
                    record = self._build_task_record(
                        study_id,
                        "behavioral",
                        idx,
                        task_data,
                        modalities,
                        study_objective,
                        publication_id,
                    )
                    if record:
                        self.tasks.append(record)

        filtered_tasks: List[Dict[str, Any]] = []
        for task in self.tasks:
            if task["task_type"] == "fmri" and not include_fmri:
                continue
            if task["task_type"] == "behavioral" and not include_behavioral:
                continue
            filtered_tasks.append(task)
        return filtered_tasks

    def prepare_collections(self) -> List[Dict[str, Any]]:
        if not self.studies:
            self.load_studies()

        collections: List[Dict[str, Any]] = []
        for study in self.studies:
            study_id = study["study_id"]
            payload = self.study_payloads.get(study_id) or {}
            info = payload.get("info") or {}
            results = payload.get("results") or {}
            title = study.get("title") or self._derive_study_title(
                info, results, study.get("study_objective")
            )
            name = (
                title or study.get("study_objective") or f"Neurostore Study {study_id}"
            )
            collection_id = study.get("collection_id") or self._collection_node_id(
                study_id
            )
            record = {
                "id": collection_id,
                "name": name,
                "title": title,
                "study_id": study_id,
                "publication_id": study.get("publication_id"),
                "modalities": study.get("modalities", []),
                "study_objective": study.get("study_objective"),
                "identifiers": study.get("identifiers", {}),
                "stats": study.get("stats", {}),
                "ingest_date": study.get("ingest_date"),
                "ingested_at": self.ingested_at,
                "valid": study.get("valid"),
                "exclude": study.get("exclude"),
                "source": "neurostore",
            }
            collections.append(record)
        return collections

    def prepare_publications(self) -> List[Dict[str, Any]]:
        if not self.studies:
            self.load_studies()

        publications: Dict[str, Dict[str, Any]] = {}
        for study in self.studies:
            pub_id = study.get("publication_id") or self._resolve_publication_id(study)
            identifiers = study.get("identifiers", {})
            raw_title = study.get("title") or study.get("study_title")
            if not raw_title:
                raw_title = study.get("study_objective")
            title = _coerce_str(raw_title) if raw_title else None
            record = {
                "id": pub_id,
                "pmid": identifiers.get("pmid"),
                "doi": identifiers.get("doi"),
                "neurostore_id": identifiers.get("dbid", study["study_id"]),
                "source": "neurostore",
                "modalities": study.get("modalities", []),
                "study_objective": study.get("study_objective"),
                "exclude": study.get("exclude"),
                "valid": study.get("valid"),
                "ingest_date": study.get("ingest_date"),
                "inputs": study.get("inputs", {}),
                "ingested_at": self.ingested_at,
                "title": title,
            }
            publications[pub_id] = record
        return list(publications.values())

    def prepare_task_nodes(
        self,
        include_fmri: bool = True,
        include_behavioral: bool = True,
    ) -> List[Dict[str, Any]]:
        tasks = self.extract_tasks(
            include_fmri=include_fmri,
            include_behavioral=include_behavioral,
        )

        nodes: List[Dict[str, Any]] = []
        for task in tasks:
            node_id = f"neurostore_task:{task['task_uid']}"
            node = {
                "id": node_id,
                "name": task.get("name_original") or task.get("name"),
                "label": task.get("name_original") or task.get("name"),
                "description": task.get("description_original"),
                "description_normalized": task.get("description"),
                "collection_id": task.get("collection_id"),
                "task_type": task["task_type"],
                "task_index": task["task_index"],
                "study_id": task["study_id"],
                "publication_id": task["publication_id"],
                "source": "neurostore",
                "concepts": task.get("concepts_original", []),
                "concepts_normalized": task.get("concepts_normalized", []),
                "domains": task.get("domains_original", []),
                "domains_normalized": task.get("domains_normalized", []),
                "conditions": task.get("conditions_original", []),
                "conditions_normalized": task.get("conditions", []),
                "metrics": task.get("metrics_original", []),
                "metrics_normalized": task.get("metrics", []),
                "task_design": task.get("task_design", []),
                "task_design_normalized": task.get("design_normalized", []),
                "design_details": task.get("design_details_original"),
                "design_details_normalized": task.get("design_details"),
                "modality": task.get("modality", []),
                "study_objective": task.get("study_objective"),
                "resting_state": task.get("resting_state"),
                "resting_state_metadata": task.get("resting_state_metadata"),
                "task_duration": task.get("task_duration"),
                "text_name_description": task.get("text_name_description"),
                "text_with_concepts": task.get("text_with_concepts"),
                "ingested_at": self.ingested_at,
                "taxonomy_match": task.get("taxonomy_match"),
                "canonical_task_id": task.get("canonical_task_id"),
                "canonical_task_label": task.get("canonical_task_label"),
                "match_method": task.get("match_method"),
                "match_confidence": task.get("match_confidence"),
                "family_id": task.get("family_id"),
                "family_label": task.get("family_label"),
                "family_slug": task.get("family_slug"),
                "family_source": task.get("family_source"),
                "family_onvoc_uri": task.get("family_onvoc_uri"),
            }
            nodes.append(node)
        return nodes

    def prepare_relationships(
        self,
        relationship_type: str = "REPORTS_TASK",
        *,
        start_field: str = "publication_id",
    ) -> List[Dict[str, Any]]:
        if not self.tasks:
            self.extract_tasks()

        relationships: List[Dict[str, Any]] = []
        for task in self.tasks:
            start_id = task.get(start_field)
            if not start_id:
                continue
            end_id = f"neurostore_task:{task['task_uid']}"
            props: Dict[str, Any] = {
                "source": "neurostore",
                "task_type": task["task_type"],
                "task_index": task["task_index"],
                "raw_label": task.get("name_original") or task.get("name"),
            }
            if task.get("match_method"):
                props["match_method"] = task.get("match_method")
            if task.get("match_confidence") is not None:
                props["match_confidence"] = task.get("match_confidence")
            if task.get("canonical_task_id"):
                props["canonical_task_id"] = task.get("canonical_task_id")
                props["canonical_task_label"] = task.get("canonical_task_label")
            if task.get("family_id"):
                props["family_id"] = task.get("family_id")
                props["family_label"] = task.get("family_label")
                props["family_source"] = task.get("family_source")
                props["family_onvoc_uri"] = task.get("family_onvoc_uri")
            props["task_uid"] = task.get("task_uid")
            relationships.append(
                {
                    "start": start_id,
                    "end": end_id,
                    "type": relationship_type,
                    "properties": props,
                }
            )
        return relationships

    def get_statistics(self) -> Dict[str, Any]:
        if not self.studies:
            self.load_studies()
        if not self.tasks:
            self.extract_tasks()

        fmri_count = sum(1 for task in self.tasks if task["task_type"] == "fmri")
        behavioral_count = sum(
            1 for task in self.tasks if task["task_type"] == "behavioral"
        )
        concept_set = {
            concept
            for task in self.tasks
            for concept in task.get("concepts_normalized", [])
        }
        domain_set = {
            domain
            for task in self.tasks
            for domain in task.get("domains_normalized", [])
        }

        return {
            "studies": len(self.studies),
            "tasks": len(self.tasks),
            "fmri_tasks": fmri_count,
            "behavioral_tasks": behavioral_count,
            "unique_concepts": len(concept_set),
            "unique_domains": len(domain_set),
            "skipped_invalid": len(self.skipped_invalid),
            "errors": len(self.errors),
        }

    def export_for_kg(
        self,
        include_fmri: bool = True,
        include_behavioral: bool = True,
    ) -> Dict[str, Any]:
        publications = self.prepare_publications()
        collections = self.prepare_collections()
        task_nodes = self.prepare_task_nodes(
            include_fmri=include_fmri,
            include_behavioral=include_behavioral,
        )
        tasks = self.extract_tasks(
            include_fmri=include_fmri,
            include_behavioral=include_behavioral,
        )

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        seen_publications: set[str] = set()
        for publication in publications:
            if publication["id"] in seen_publications:
                continue
            seen_publications.add(publication["id"])
            nodes.append(
                {
                    "id": publication["id"],
                    "type": "Publication",
                    "properties": publication,
                }
            )

        seen_collections: set[str] = set()
        for collection in collections:
            if collection["id"] in seen_collections:
                continue
            seen_collections.add(collection["id"])
            nodes.append(
                {
                    "id": collection["id"],
                    "type": "Collection",
                    "properties": collection,
                }
            )

        for task_node in task_nodes:
            nodes.append(
                {
                    "id": task_node["id"],
                    "type": "Task",
                    "properties": task_node,
                }
            )

        pub_relationships = self.prepare_relationships()
        collection_relationships = self.prepare_relationships(
            start_field="collection_id"
        )
        combined_relationships = pub_relationships + collection_relationships
        edges.extend(
            {
                "source": rel["start"],
                "target": rel["end"],
                "type": rel["type"],
                "properties": rel.get("properties", {}),
            }
            for rel in combined_relationships
        )

        metadata = {
            "generated_at": self.ingested_at,
            "source": "neurostore",
            "statistics": self.get_statistics(),
        }

        return {"nodes": nodes, "edges": edges, "metadata": metadata}

    def to_dataframe(
        self,
        include_fmri: bool = True,
        include_behavioral: bool = True,
    ):
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pandas is required to convert Neurostore tasks to a DataFrame"
            ) from exc

        tasks = self.extract_tasks(
            include_fmri=include_fmri,
            include_behavioral=include_behavioral,
        )
        return pd.DataFrame(tasks)
