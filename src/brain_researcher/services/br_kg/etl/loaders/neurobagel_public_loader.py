#!/usr/bin/env python3
"""
Neurobagel public node loader.

Pulls dataset- and subject-level metadata from the Neurobagel federation
and converts it into aggregated phenotype summaries without creating
per-subject nodes in the knowledge graph.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from itertools import islice
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

import logging

logger = logging.getLogger(__name__)

FEDERATION_NODES_URL = "https://federate.neurobagel.org/nodes"
DEFAULT_BATCH_SIZE = 25


@dataclass
class DatasetSummary:
    dataset_uuid: str
    dataset_name: str
    portal_uri: Optional[str]
    openneuro_id: Optional[str]
    total_subjects_reported: Optional[int]
    records_protected: bool
    unique_subjects: int
    imaging_sessions: int
    phenotypic_sessions: int
    phenotypes: List[Dict[str, Any]] = field(default_factory=list)
    cohort_metadata: Optional[Dict[str, Any]] = None


def _slugify(value: str) -> str:
    """Convert a string into a safe identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return cleaned.strip("_").lower() or "value"


def _clean_term(value: Any) -> Optional[str]:
    """Normalize Neurobagel vocabulary strings for readability."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text.startswith("http"):
        if "#" in text:
            return text.rsplit("#", 1)[-1]
        return text.rstrip("/").rsplit("/", 1)[-1]
    if ":" in text:
        return text.split(":", 1)[-1]
    return text


def _try_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _chunked(seq: List[str], size: int) -> Iterable[List[str]]:
    """Yield successive chunks from a list."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _build_group_count_bucket(
    participant_counts: Counter[str],
    row_counts: Counter[str],
    *,
    min_group_count: int = 5,
) -> Dict[str, Any]:
    participant_counts_dict = {str(key): int(value) for key, value in participant_counts.items()}
    row_counts_dict = {str(key): int(value) for key, value in row_counts.items()}
    underpowered = {
        key: int(value)
        for key, value in participant_counts_dict.items()
        if int(value) < min_group_count
    }
    return {
        "participant_counts": participant_counts_dict,
        "row_counts": row_counts_dict,
        "missing_participants": 0,
        "missing_rows": 0,
        "n_levels": len(participant_counts_dict),
        "underpowered_groups": underpowered,
    }


def _rollup_group_counts(group_counts_blocks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rolled_up: Dict[str, Dict[str, Any]] = {}
    for block in group_counts_blocks:
        for key, payload in (block or {}).items():
            bucket = rolled_up.setdefault(
                str(key),
                {
                    "participant_counts": {},
                    "row_counts": {},
                    "missing_participants": 0,
                    "missing_rows": 0,
                    "n_levels": 0,
                    "underpowered_groups": {},
                },
            )
            for level, count in (payload.get("participant_counts") or {}).items():
                bucket["participant_counts"][str(level)] = int(
                    bucket["participant_counts"].get(str(level), 0)
                ) + int(count)
            for level, count in (payload.get("row_counts") or {}).items():
                bucket["row_counts"][str(level)] = int(
                    bucket["row_counts"].get(str(level), 0)
                ) + int(count)
            bucket["missing_participants"] = int(bucket["missing_participants"]) + int(
                payload.get("missing_participants", 0) or 0
            )
            bucket["missing_rows"] = int(bucket["missing_rows"]) + int(
                payload.get("missing_rows", 0) or 0
            )
            bucket["n_levels"] = len(bucket["participant_counts"])
            bucket["underpowered_groups"] = {
                level: int(count)
                for level, count in bucket["participant_counts"].items()
                if int(count) < 5
            }
    return rolled_up


def _build_cohort_metadata(
    *,
    participant_scope: str,
    aggregation_scope: str,
    group_counts: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not group_counts:
        return None
    resolved_group_keys = sorted(str(key) for key in group_counts)
    return {
        "schema_version": "br-cohort-metadata-v1",
        "participant_id_scope": participant_scope,
        "aggregation_scope": aggregation_scope,
        "group_audit": {
            "requested_group_keys": list(resolved_group_keys),
            "resolved_group_keys": list(resolved_group_keys),
            "missing_group_keys": [],
            "group_counts": group_counts,
        },
    }


def summarize_subject_records(record: Dict[str, Any]) -> Optional[DatasetSummary]:
    """
    Aggregate subject-level data from a Neurobagel dataset record.

    Returns None when subject data is unavailable (e.g., protected datasets).
    """
    subject_data = record.get("subject_data")
    if not subject_data or isinstance(subject_data, str):
        return None

    per_subject: Dict[str, Dict[str, Any]] = {}
    imaging_sessions = 0
    phenotypic_sessions = 0
    imaging_modalities = Counter()
    sex_rows = Counter()
    group_rows = Counter()

    # Iterate over session rows
    for session in subject_data:
        subject_id = session.get("sub_id")
        session_type = session.get("session_type") or ""
        session_type_lower = session_type.lower()

        if subject_id:
            current = per_subject.setdefault(
                subject_id,
                {
                    "ages": [],
                    "sex": None,
                    "groups": set(),
                    "diagnoses": Counter(),
                    "assessments": Counter(),
                },
            )

            age_value = _try_float(session.get("age"))
            if age_value is not None:
                current["ages"].append(age_value)

            sex_value = session.get("sex")
            if sex_value and current["sex"] is None:
                current["sex"] = _clean_term(sex_value)
            cleaned_sex_value = _clean_term(sex_value)
            if cleaned_sex_value:
                sex_rows[cleaned_sex_value] += 1

            group_value = _clean_term(session.get("subject_group"))
            if group_value:
                current["groups"].add(group_value)
                group_rows[group_value] += 1

            diagnoses = session.get("diagnosis") or []
            for diagnosis in diagnoses:
                cleaned = _clean_term(diagnosis)
                if cleaned:
                    current["diagnoses"][cleaned] += 1

            assessments = session.get("assessment") or []
            for assessment in assessments:
                cleaned = _clean_term(assessment)
                if cleaned:
                    current["assessments"][cleaned] += 1

        if "phenotypic" in session_type_lower:
            phenotypic_sessions += 1
        if "imaging" in session_type_lower:
            imaging_sessions += 1

        for modal in session.get("image_modal") or []:
            cleaned = _clean_term(modal)
            if cleaned:
                imaging_modalities[cleaned] += 1

    # Aggregate demographics
    ages: List[float] = []
    sexes = Counter()
    groups = Counter()
    diagnoses = Counter()
    assessments = Counter()

    for subject in per_subject.values():
        if subject["ages"]:
            # take median per subject to avoid double counting across sessions
            ages.append(statistics.median(subject["ages"]))

        sex_value = subject["sex"]
        if sex_value:
            sexes[sex_value] += 1

        for group in subject["groups"]:
            groups[group] += 1

        diagnoses.update(subject["diagnoses"])
        assessments.update(subject["assessments"])

    phenotypes: List[Dict[str, Any]] = []

    if ages:
        mean_val = statistics.fmean(ages)
        summary = {
            "count": len(ages),
            "min": min(ages),
            "max": max(ages),
            "mean": mean_val,
        }
        if len(ages) >= 2:
            summary["stdev"] = statistics.stdev(ages)
        summary["median"] = statistics.median(ages)
        phenotypes.append(
            {
                "name": "Age",
                "category": "demographics",
                "measurement_type": "continuous",
                "numeric_summary": summary,
                "total_observations": len(ages),
            }
        )

    if sexes:
        phenotypes.append(
            {
                "name": "Sex",
                "category": "demographics",
                "measurement_type": "categorical",
                "value_counts": dict(sexes),
                "total_observations": sum(sexes.values()),
            }
        )

    if groups:
        phenotypes.append(
            {
                "name": "Subject Group",
                "category": "demographics",
                "measurement_type": "categorical",
                "value_counts": dict(groups),
                "total_observations": sum(groups.values()),
            }
        )

    if diagnoses:
        phenotypes.append(
            {
                "name": "Diagnosis",
                "category": "clinical",
                "measurement_type": "categorical",
                "value_counts": dict(diagnoses),
                "total_observations": sum(diagnoses.values()),
            }
        )

    if assessments:
        phenotypes.append(
            {
                "name": "Assessment",
                "category": "assessment",
                "measurement_type": "categorical",
                "value_counts": dict(assessments),
                "total_observations": sum(assessments.values()),
            }
        )

    if imaging_modalities:
        phenotypes.append(
            {
                "name": "Imaging Modality",
                "category": "imaging",
                "measurement_type": "categorical_multi",
                "value_counts": dict(imaging_modalities),
                "total_observations": sum(imaging_modalities.values()),
            }
        )

    cohort_metadata = _build_cohort_metadata(
        participant_scope="dataset_subject_local",
        aggregation_scope="dataset_summary_from_subject_rows",
        group_counts={
            key: value
            for key, value in {
                "sex": _build_group_count_bucket(sexes, sex_rows) if sexes else None,
                "subject_group": _build_group_count_bucket(groups, group_rows) if groups else None,
            }.items()
            if value
        },
    )

    dataset_uuid = record.get("dataset_uuid", "")
    portal_uri = record.get("dataset_portal_uri")
    openneuro_id = None
    if portal_uri:
        match = re.search(r"(ds\d{6})", portal_uri)
        if match:
            openneuro_id = match.group(1)

    summary = DatasetSummary(
        dataset_uuid=dataset_uuid,
        dataset_name=record.get("dataset_name", ""),
        portal_uri=portal_uri,
        openneuro_id=openneuro_id,
        total_subjects_reported=record.get("dataset_total_subjects"),
        records_protected=bool(record.get("records_protected")),
        unique_subjects=len(per_subject),
        imaging_sessions=imaging_sessions,
        phenotypic_sessions=phenotypic_sessions,
        phenotypes=phenotypes,
        cohort_metadata=cohort_metadata,
    )
    return summary


class NeurobagelPublicLoader:
    """Loader that ingests Neurobagel public node metadata into the KG."""

    def __init__(
        self,
        db: Any,
        session: Optional[requests.Session] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        nodes_endpoint: str = FEDERATION_NODES_URL,
        offline_cache_dir: Optional[str | Path] = None,
    ):
        self.db = db
        self.session = session or requests.Session()
        self.batch_size = max(1, batch_size)
        self.nodes_endpoint = nodes_endpoint
        self.offline_cache_dir = Path(offline_cache_dir).resolve() if offline_cache_dir else None
        self.stats: Dict[str, Any] = {
            "nodes_queried": 0,
            "datasets_discovered": 0,
            "datasets_skipped": 0,
            "protected_datasets": 0,
            "subject_groups_created": 0,
            "phenotypes_created": 0,
            "relationships_created": 0,
            "cohort_metadata": {
                "schema_version": "br-cohort-metadata-v1",
                "participant_id_scope": "dataset_subject_local",
                "aggregation_scope": "loader_rollup_from_dataset_summaries",
                "group_audit": {
                    "requested_group_keys": [],
                    "resolved_group_keys": [],
                    "missing_group_keys": [],
                    "group_counts": {},
                },
            },
        }

    def _get_node_cache_dir(self, node_name: str) -> Optional[Path]:
        if not self.offline_cache_dir:
            return None
        return self.offline_cache_dir / _slugify(node_name)

    def load(
        self,
        include_nodes: Optional[List[str]] = None,
        exclude_nodes: Optional[List[str]] = None,
        dataset_limit_per_node: Optional[int] = None,
    ) -> Dict[str, Any]:
        nodes = self._fetch_nodes(include_nodes, exclude_nodes)
        for node in nodes:
            try:
                self._process_node(node, dataset_limit_per_node)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "Failed to process Neurobagel node %s: %s", node.get("NodeName"), exc
                )
                self.stats.setdefault("node_errors", []).append(
                    {"node": node.get("NodeName"), "error": str(exc)}
                )
        return self.stats

    # ------------------------------------------------------------------ helpers
    def _fetch_nodes(
        self,
        include_nodes: Optional[List[str]],
        exclude_nodes: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        resp = self.session.get(self.nodes_endpoint, timeout=30)
        resp.raise_for_status()
        nodes: List[Dict[str, Any]] = resp.json()
        include_set = {name.lower() for name in include_nodes} if include_nodes else None
        exclude_set = {name.lower() for name in exclude_nodes} if exclude_nodes else set()

        filtered: List[Dict[str, Any]] = []
        for node in nodes:
            node_name = node.get("NodeName", "")
            if include_set and node_name.lower() not in include_set:
                continue
            if node_name.lower() in exclude_set:
                continue
            filtered.append(node)

        self.stats["nodes_queried"] = len(filtered)
        return filtered

    def _process_node(
        self,
        node: Dict[str, Any],
        dataset_limit_per_node: Optional[int],
    ) -> None:
        node_name = node.get("NodeName", "unknown")
        raw_api_url = node.get("ApiURL")
        base_url = None
        if isinstance(raw_api_url, str):
            candidate = raw_api_url.strip()
            if candidate and candidate.lower() not in {"none", "null"}:
                base_url = candidate
        cache_dir = self._get_node_cache_dir(node_name)
        if not base_url and not cache_dir:
            logger.warning(
                "Skipping Neurobagel node without ApiURL and no offline cache: %s",
                node_name,
            )
            return

        datasets = self._fetch_datasets(base_url, node_name)
        self.stats["datasets_discovered"] += len(datasets)
        if dataset_limit_per_node is not None:
            datasets = list(islice(datasets, dataset_limit_per_node))

        uuid_lookup = [dataset.get("dataset_uuid") for dataset in datasets if dataset.get("dataset_uuid")]
        if not uuid_lookup:
            logger.info("No datasets with UUIDs for node %s", node_name)
            return

        for chunk in _chunked(uuid_lookup, self.batch_size):
            records = self._fetch_subjects(base_url, chunk, node_name)
            for record in records:
                summary = summarize_subject_records(record)
                if summary is None:
                    self.stats["datasets_skipped"] += 1
                    if record.get("records_protected"):
                        self.stats["protected_datasets"] += 1
                    continue
                self._persist_summary(record, summary, node_name)

    def _fetch_datasets(
        self,
        base_url: Optional[str],
        node_name: str,
    ) -> List[Dict[str, Any]]:
        cache_dir = self._get_node_cache_dir(node_name)
        if cache_dir:
            datasets_path = cache_dir / "datasets.json"
            if datasets_path.exists():
                try:
                    return json.loads(datasets_path.read_text())
                except Exception as exc:  # pragma: no cover
                    logger.warning("Failed to read cached datasets for %s: %s", node_name, exc)

        if not base_url:
            logger.warning(
                "No ApiURL for Neurobagel node %s; using offline cache only", node_name
            )
            return []

        parsed = urlparse(base_url)
        if not parsed.scheme:
            logger.warning(
                "Invalid ApiURL for Neurobagel node %s: %s", node_name, base_url
            )
            return []

        logger.debug("Fetching Neurobagel datasets from %s", base_url)
        url = urljoin(base_url, "datasets")
        resp = self.session.post(url, json={}, timeout=60)
        resp.raise_for_status()
        datasets = resp.json()
        if not isinstance(datasets, list):
            return []

        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                (cache_dir / "datasets.json").write_text(json.dumps(datasets, indent=2))
            except Exception as exc:  # pragma: no cover
                logger.debug("Failed to write dataset cache for %s: %s", node_name, exc)

        return datasets

    def _fetch_subjects(
        self,
        base_url: Optional[str],
        uuids: List[str],
        node_name: str,
    ) -> List[Dict[str, Any]]:
        cache_dir = self._get_node_cache_dir(node_name)
        records: List[Dict[str, Any]] = []
        missing: List[str] = []

        if cache_dir:
            subjects_dir = cache_dir / "subjects"
            for uuid in uuids:
                if not uuid:
                    continue
                path = subjects_dir / f"{_slugify(uuid)}.json"
                if path.exists():
                    try:
                        records.append(json.loads(path.read_text()))
                        continue
                    except Exception as exc:  # pragma: no cover
                        logger.warning("Failed to read cached subjects for %s (%s): %s", node_name, uuid, exc)
                missing.append(uuid)
        else:
            missing = [uuid for uuid in uuids if uuid]

        if not missing:
            return records

        if not base_url:
            logger.warning(
                "Skipping live subject fetch for %s; ApiURL missing", node_name
            )
            return records

        parsed = urlparse(base_url)
        if not parsed.scheme:
            logger.warning(
                "Invalid ApiURL for Neurobagel node %s (subjects): %s",
                node_name,
                base_url,
            )
            return records

        logger.debug(
            "Fetching Neurobagel subjects for %s from %s (missing=%d)",
            node_name,
            base_url,
            len(missing),
        )
        url = urljoin(base_url, "subjects")
        payload = {"dataset_uuids": missing}
        resp = self.session.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        fetched = resp.json()
        if not isinstance(fetched, list):
            return records

        if cache_dir:
            subjects_dir = cache_dir / "subjects"
            subjects_dir.mkdir(parents=True, exist_ok=True)
            for entry in fetched:
                uuid = entry.get("dataset_uuid")
                if not uuid:
                    continue
                path = subjects_dir / f"{_slugify(uuid)}.json"
                try:
                    path.write_text(json.dumps(entry, indent=2))
                except Exception as exc:  # pragma: no cover
                    logger.debug("Failed to write subject cache for %s (%s): %s", node_name, uuid, exc)

        records.extend(fetched)
        return records

    # ---------------------------------------------------------- persistence ----
    def _persist_summary(
        self,
        raw_record: Dict[str, Any],
        summary: DatasetSummary,
        node_name: str,
    ) -> None:
        del raw_record
        self._merge_summary_cohort_metadata(summary)
        dataset_node_id = self._ensure_dataset_node(summary, node_name)
        if not dataset_node_id:
            return

        subject_group_id = self._ensure_subject_group(summary, dataset_node_id, node_name)

        for phenotype in summary.phenotypes:
            pheno_id = self._ensure_phenotype_node(
                phenotype, summary, subject_group_id, node_name
            )
            if not pheno_id:
                continue
            if not self._relationship_exists(subject_group_id, pheno_id, "HAS_PHENOTYPE"):
                rel_id = self.db.create_relationship(
                    subject_group_id,
                    pheno_id,
                    "HAS_PHENOTYPE",
                    {
                        "source": f"neurobagel:{node_name}",
                        "aggregation_level": "dataset",
                    },
                )
                if rel_id:
                    self.stats["relationships_created"] += 1

    def _ensure_dataset_node(
        self, summary: DatasetSummary, node_name: str
    ) -> Optional[str]:
        existing_ids: List[str] = []

        if summary.openneuro_id:
            matches = self.db.find_nodes(
                labels="Dataset", properties={"dataset_id": summary.openneuro_id}
            )
            existing_ids.extend(node_id for node_id, _ in matches)

        if not existing_ids:
            matches = self.db.find_nodes(
                labels="Dataset", properties={"dataset_uuid": summary.dataset_uuid}
            )
            existing_ids.extend(node_id for node_id, _ in matches)

        node_id: Optional[str] = existing_ids[0] if existing_ids else None

        if node_id:
            return node_id

        node_id = f"neurobagel_dataset_{_slugify(summary.dataset_uuid or summary.dataset_name)}"

        props = {
            "name": summary.dataset_name,
            "dataset_uuid": summary.dataset_uuid,
            "portal_uri": summary.portal_uri,
            "openneuro_id": summary.openneuro_id,
            "source": f"neurobagel:{node_name}",
            "total_subjects_reported": summary.total_subjects_reported,
        }
        if summary.cohort_metadata:
            props["cohort_metadata"] = summary.cohort_metadata
            props["audit_group_keys"] = list(
                ((summary.cohort_metadata.get("group_audit") or {}).get("resolved_group_keys"))
                or []
            )

        try:
            self.db.create_node("Dataset", props, node_id=node_id)
        except ValueError as exc:
            if "Constraint violation" in str(exc):
                # Race condition: retrieve existing node
                matches = self.db.find_nodes(labels="Dataset", properties={"dataset_uuid": summary.dataset_uuid})
                if matches:
                    return matches[0][0]
                return node_id
            logger.error("Failed to create Dataset node for %s: %s", summary.dataset_uuid, exc)
            return None

        return node_id

    def _ensure_subject_group(
        self,
        summary: DatasetSummary,
        dataset_node_id: str,
        node_name: str,
    ) -> str:
        group_id = f"neurobagel_{_slugify(summary.dataset_uuid)}_group"
        props = {
            "name": f"{summary.dataset_name} (Neurobagel)",
            "dataset_uuid": summary.dataset_uuid,
            "source": f"neurobagel:{node_name}",
            "unique_subjects": summary.unique_subjects,
            "imaging_sessions": summary.imaging_sessions,
            "phenotypic_sessions": summary.phenotypic_sessions,
            "records_protected": summary.records_protected,
        }
        if summary.cohort_metadata:
            props["cohort_metadata"] = summary.cohort_metadata
            props["audit_group_keys"] = list(
                ((summary.cohort_metadata.get("group_audit") or {}).get("resolved_group_keys"))
                or []
            )
        try:
            self.db.create_node("SubjectGroup", props, node_id=group_id)
            self.stats["subject_groups_created"] += 1
        except ValueError as exc:
            if "Constraint violation" not in str(exc):
                logger.error("Failed to create SubjectGroup for %s: %s", summary.dataset_uuid, exc)

        if not self._relationship_exists(dataset_node_id, group_id, "INCLUDES"):
            rel_id = self.db.create_relationship(
                dataset_node_id,
                group_id,
                "INCLUDES",
                {"source": f"neurobagel:{node_name}"},
            )
            if rel_id:
                self.stats["relationships_created"] += 1

        return group_id

    def _ensure_phenotype_node(
        self,
        phenotype: Dict[str, Any],
        summary: DatasetSummary,
        subject_group_id: str,
        node_name: str,
    ) -> Optional[str]:
        slug = _slugify(phenotype.get("name", "phenotype"))
        pheno_id = f"{subject_group_id}_{slug}"
        props = {
            "name": phenotype.get("name", "Unknown"),
            "category": phenotype.get("category", "unknown"),
            "measurement_type": phenotype.get("measurement_type"),
            "dataset_uuid": summary.dataset_uuid,
            "source": f"neurobagel:{node_name}",
            "total_observations": phenotype.get("total_observations"),
        }
        if "numeric_summary" in phenotype:
            props["numeric_summary"] = phenotype["numeric_summary"]
        if "value_counts" in phenotype:
            props["value_counts"] = phenotype["value_counts"]

        try:
            self.db.create_node("Phenotype", props, node_id=pheno_id)
            self.stats["phenotypes_created"] += 1
        except ValueError as exc:
            if "Constraint violation" not in str(exc):
                logger.error(
                    "Failed to create Phenotype %s for %s: %s",
                    phenotype.get("name"),
                    summary.dataset_uuid,
                    exc,
                )
                return None
        return pheno_id

    def _relationship_exists(self, start: str, end: str, rel_type: str) -> bool:
        existing = self.db.find_relationships(start_node=start, end_node=end, rel_type=rel_type)
        return bool(existing)

    def _merge_summary_cohort_metadata(self, summary: DatasetSummary) -> None:
        if not summary.cohort_metadata:
            return
        stats_cohort = self.stats["cohort_metadata"]
        stats_group_audit = stats_cohort.setdefault("group_audit", {})
        summary_group_audit = summary.cohort_metadata.get("group_audit") or {}

        requested = set(stats_group_audit.get("requested_group_keys") or [])
        requested.update(summary_group_audit.get("requested_group_keys") or [])
        stats_group_audit["requested_group_keys"] = sorted(str(key) for key in requested)

        resolved = set(stats_group_audit.get("resolved_group_keys") or [])
        resolved.update(summary_group_audit.get("resolved_group_keys") or [])
        stats_group_audit["resolved_group_keys"] = sorted(str(key) for key in resolved)

        missing = set(stats_group_audit.get("missing_group_keys") or [])
        missing.update(summary_group_audit.get("missing_group_keys") or [])
        stats_group_audit["missing_group_keys"] = sorted(str(key) for key in missing)

        stats_group_audit["group_counts"] = _rollup_group_counts(
            [
                stats_group_audit.get("group_counts") or {},
                summary_group_audit.get("group_counts") or {},
            ]
        )


def load_neurobagel_public(db: Any, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Entry point used by the ingestion pipeline.

    Example config:
        {
            "include_nodes": ["OpenNeuro", "International Neuroimaging Data-sharing Initiative"],
            "exclude_nodes": ["Quebec Parkinson Network"],
            "dataset_limit_per_node": 10,
            "batch_size": 20,
            "offline_cache_dir": "data/br-kg/raw/neurobagel_public",
        }
    """
    config = config or {}
    nodes_endpoint = config.get("nodes_endpoint") or FEDERATION_NODES_URL
    if not nodes_endpoint:
        logger.warning(
            "Neurobagel public loader received no nodes endpoint; defaulting to %s",
            FEDERATION_NODES_URL,
        )
        nodes_endpoint = FEDERATION_NODES_URL

    loader = NeurobagelPublicLoader(
        db,
        batch_size=config.get("batch_size", DEFAULT_BATCH_SIZE),
        nodes_endpoint=nodes_endpoint,
        offline_cache_dir=config.get("offline_cache_dir"),
    )
    stats = loader.load(
        include_nodes=config.get("include_nodes"),
        exclude_nodes=config.get("exclude_nodes"),
        dataset_limit_per_node=config.get("dataset_limit_per_node"),
    )
    return stats
