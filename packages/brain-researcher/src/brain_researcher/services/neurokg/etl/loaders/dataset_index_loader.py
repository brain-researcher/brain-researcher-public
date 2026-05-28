#!/usr/bin/env python3
"""
Dataset Index Loader
--------------------

Ingests curated dataset metadata from a JSON index into the BR-KG graph.
Each dataset entry becomes a `Dataset` node with provenance back to the index
and optional storage hints resolved from `data_paths.yaml`. Task labels are
matched against the layered taxonomy (see `brain_researcher.semantics.taxonomy`)
and connected to canonical `Task` nodes via `HAS_TASK` relationships.

Usage (CLI):
    python -m brain_researcher.services.neurokg.etl.loaders.dataset_index_loader \\
        --index "$BR_DATA_INDEX_PATH"
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from brain_researcher.config.mapping_resolver import get_repo_root
from brain_researcher.semantics.taxonomy.matcher import TaskMatcher, normalize_text
from brain_researcher.services.neurokg.graph.graph_database import NeuroKGGraphDB
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db
from brain_researcher.services.neurokg.utils.task_taxonomy import (
    TaskMatchResult,
    TaskTaxonomyResolver,
)

logger = logging.getLogger(__name__)


def _safe_path_exists(path_obj: Path) -> tuple[bool, Optional[str]]:
    """Return (exists, error_message) guarding against filesystem IO errors."""
    try:
        return path_obj.exists(), None
    except OSError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


class DatasetIndexLoader:
    """Loader that turns dataset index entries into BR-KG nodes."""

    def __init__(
        self,
        index_path: Path | str,
        config_path: Path | str | None = None,
        *,
        db: NeuroKGGraphDB | None = None,
        matcher: TaskMatcher | None = None,
    ):
        self.index_path = Path(index_path)
        if not self.index_path.exists():
            raise FileNotFoundError(f"Dataset index not found: {self.index_path}")

        self.config_path = Path(config_path) if config_path else None
        self.config: Dict[str, Any] = self._load_config(self.config_path)

        # BR-KG is Neo4j-only; connection is configured via NEO4J_URI/NEO4J_PASSWORD.
        # Older scripts passed db_path; that is ignored by the Neo4j backend.
        self.db = db or require_neo4j_db(preload_cache=False)
        self.task_resolver = TaskTaxonomyResolver(self.db, matcher)

        self.stats: Dict[str, Any] = {
            "datasets_processed": 0,
            "datasets_upserted": 0,
            "tasks_matched": 0,
            "tasks_unmatched": 0,
            "relationships_created": 0,
            "task_nodes_created": 0,
            "errors": [],
        }

    @staticmethod
    def _load_config(config_path: Optional[Path]) -> Dict[str, Any]:
        """Load YAML configuration if available."""
        if not config_path:
            return {}
        if not config_path.exists():
            logger.warning("Config path %s does not exist; continuing with defaults", config_path)
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to read data paths config: %s", exc)
            return {}

    def load(self) -> Dict[str, Any]:
        """Load all datasets from the index file."""
        logger.info("Loading dataset index from %s", self.index_path)
        index_payload = self._load_index()
        metadata = index_payload.get("metadata", {})
        datasets = index_payload.get("datasets", {})

        for dataset_id, dataset_info in datasets.items():
            try:
                self._ingest_dataset(dataset_id, dataset_info, metadata)
                self.stats["datasets_processed"] += 1
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Failed to ingest dataset %s", dataset_id)
                self.stats["errors"].append({"dataset": dataset_id, "error": str(exc)})

        # Persist outstanding SQLite writes
        self.db.commit()

        logger.info(
            "Dataset index ingestion complete: %s datasets processed, %s upserts, %s task links",
            self.stats["datasets_processed"],
            self.stats["datasets_upserted"],
            self.stats["relationships_created"],
        )
        self.stats["task_nodes_created"] = self.task_resolver.stats["canonical_created"]
        return dict(self.stats)

    def _load_index(self) -> Dict[str, Any]:
        """Read and parse the dataset index JSON."""
        with open(self.index_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _ingest_dataset(
        self,
        dataset_id: str,
        dataset_info: Dict[str, Any],
        metadata: Dict[str, Any],
    ):
        """Create or update a Dataset node and attach task relationships."""
        dataset_id = dataset_id.strip()
        if not dataset_id:
            return

        task_entries, unmatched = self._match_tasks(dataset_info.get("tasks", []))
        node_payload = self._build_dataset_payload(
            dataset_id=dataset_id,
            dataset_info=dataset_info,
            metadata=metadata,
            task_entries=task_entries,
            unmatched=unmatched,
        )

        node_id = self.db.create_node("Dataset", node_payload, node_id=dataset_id)
        self.stats["datasets_upserted"] += 1

        if unmatched:
            self.stats["tasks_unmatched"] += len(unmatched)
        if task_entries:
            self._link_tasks(node_id, task_entries)
            self.stats["tasks_matched"] += len(task_entries)

    def _build_dataset_payload(
        self,
        dataset_id: str,
        dataset_info: Dict[str, Any],
        metadata: Dict[str, Any],
        task_entries: List[Dict[str, Any]],
        unmatched: List[str],
    ) -> Dict[str, Any]:
        """Assemble dataset node properties."""
        full_name = dataset_info.get("full_name") or dataset_id
        description = dataset_info.get("description")
        data_types = [
            dtype.strip()
            for dtype in dataset_info.get("data_types", []) or []
            if isinstance(dtype, str) and dtype.strip() and dtype.strip() != "?"
        ]

        storage_info = self._resolve_storage(dataset_id, dataset_info, metadata)
        matched_canonicals = sorted(
            {
                entry["match"]["canonical_id"]
                for entry in task_entries
                if entry["match"].get("canonical_id")
            }
        )

        payload: Dict[str, Any] = {
            "id": dataset_id,
            "name": full_name,
            "description": description,
            "data_types": data_types,
            "raw_task_labels": dataset_info.get("tasks", []),
            "matched_task_canonicals": matched_canonicals,
            "unmatched_tasks": unmatched,
            "source": "dataset_index",
            "ingest_file": str(self.index_path),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }

        if metadata:
            payload["index_metadata"] = metadata

        if storage_info:
            payload["storage"] = storage_info

        if task_entries:
            payload["task_annotations"] = [
                {
                    "original_label": entry["original"],
                    "canonical_label": entry["match"]["label"],
                    "canonical_id": entry["match"]["canonical_id"],
                    "confidence": entry["match"].get("confidence"),
                    "parameters": entry["match"].get("parameters"),
                    "match_method": entry["match"].get("match_method"),
                }
                for entry in task_entries
            ]

        return payload

    def _resolve_storage(
        self,
        dataset_id: str,
        dataset_info: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Collect potential storage locations for the dataset."""
        storage_details: Dict[str, Any] = {}

        base_location = metadata.get("location")
        candidate_paths: List[Dict[str, Any]] = []

        if base_location:
            candidate = Path(str(base_location)).expanduser() / dataset_id
            exists, error = _safe_path_exists(candidate)
            candidate_paths.append(
                {
                    "path": str(candidate),
                    "exists": exists,
                    "source": "metadata.location",
                    **({"error": error} if error else {}),
                }
            )

        config_datasets = (
            self.config.get("oak_mount", {}).get("datasets", {}) if isinstance(self.config, dict) else {}
        )
        dataset_name_norm = normalize_text(dataset_info.get("full_name", ""))
        for key, path_str in config_datasets.items():
            if not isinstance(path_str, str):
                continue
            key_norm = normalize_text(key)
            if key_norm in (normalize_text(dataset_id), dataset_name_norm):
                path_obj = Path(path_str).expanduser()
                exists, error = _safe_path_exists(path_obj)
                entry = {
                    "path": str(path_obj),
                    "exists": exists,
                    "source": f"oak_mount.datasets.{key}",
                }
                if error:
                    entry["error"] = error
                candidate_paths.append(entry)

        local_paths = self.config.get("local", {}) if isinstance(self.config, dict) else {}
        for key, path_str in local_paths.items():
            if not isinstance(path_str, str):
                continue
            if key.endswith("_dir") or key in ("cache", "processed", "bids", "neurokg"):
                continue
            key_norm = normalize_text(key)
            if key_norm in (normalize_text(dataset_id), dataset_name_norm):
                path_obj = Path(path_str).expanduser()
                exists, error = _safe_path_exists(path_obj)
                entry = {"path": str(path_obj), "exists": exists, "source": f"local.{key}"}
                if error:
                    entry["error"] = error
                candidate_paths.append(entry)

        if candidate_paths:
            storage_details["candidates"] = candidate_paths
        if base_location:
            storage_details["metadata_root"] = base_location

        return storage_details

    def _match_tasks(self, tasks: Iterable[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Match raw task labels to canonical taxonomy entries."""
        matched: List[Dict[str, Any]] = []
        unmatched: List[str] = []

        for raw_label in tasks or []:
            if not isinstance(raw_label, str):
                continue
            cleaned = raw_label.strip()
            if not cleaned or cleaned == "?" or cleaned.lower().startswith("many tasks"):
                unmatched.append(raw_label)
                continue

            match_result = self.task_resolver.match_label(cleaned)
            if match_result:
                match_payload = dict(match_result.match)
                if match_result.fallback_node_id:
                    match_payload["_fallback_node_id"] = match_result.fallback_node_id
                matched.append({"original": raw_label, "match": match_payload})
            else:
                unmatched.append(raw_label)

        return matched, unmatched

    def _link_tasks(self, dataset_node_id: str, entries: List[Dict[str, Any]]):
        """Create HAS_TASK relationships for matched tasks."""
        for entry in entries:
            match = entry["match"]
            match_result = TaskMatchResult(
                match=match,
                method=match.get("match_method", "taxonomy_rule"),
                fallback_node_id=match.get("_fallback_node_id"),
            )
            task_node_id = self.task_resolver.ensure_canonical_task(match_result)
            if not task_node_id:
                continue

            existing = self.db.find_relationships(
                start_node=dataset_node_id,
                end_node=task_node_id,
                rel_type="HAS_TASK",
            )
            if existing:
                continue

            props = {
                "source": "dataset_index",
                "original_label": entry["original"],
                "canonical_label": match.get("label"),
                "canonical_id": match.get("canonical_id"),
                "confidence": match.get("confidence"),
            }
            parameters = match.get("parameters") or {}
            if parameters:
                props["parameters"] = parameters

            created = self.db.create_relationship(
                dataset_node_id,
                task_node_id,
                "HAS_TASK",
                props,
            )
            if created:
                self.stats["relationships_created"] += 1

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest dataset index into BR-KG")
    parser.add_argument(
        "--index",
        required=True,
        help="Path to data_index.json",
    )
    parser.add_argument(
        "--config",
        default=str(get_repo_root() / "configs" / "legacy" / "data_paths.yaml"),
        help="Path to data_paths.yaml (defaults to repository config)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override BR-KG SQLite database path",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    """Command-line entry point."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    index_path = Path(args.index).expanduser()
    config_path = Path(args.config).expanduser() if args.config else None
    db_instance: Optional[NeuroKGGraphDB] = None
    if args.db:
        db_instance = NeuroKGGraphDB(str(Path(args.db).expanduser()))

    loader = DatasetIndexLoader(
        index_path=index_path,
        config_path=config_path,
        db=db_instance,
    )
    stats = loader.load()
    logger.info("Ingestion stats: %s", stats)
    return stats


if __name__ == "__main__":  # pragma: no cover - CLI
    main()
