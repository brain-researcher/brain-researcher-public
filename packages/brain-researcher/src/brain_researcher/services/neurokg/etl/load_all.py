#!/usr/bin/env python3
"""
Master Data Ingestion Script for Brain Researcher

This script provides a unified interface to load all data sources into the BR-KG database.
It handles Cognitive Atlas, PubMed, OpenNeuro, NeuroVault, NeuroSynth, WikiData, and more.

Usage:
    python -m brain_researcher.services.neurokg.etl.load_all --full
    python -m brain_researcher.services.neurokg.etl.load_all --sources ca pm
    python -m brain_researcher.services.neurokg.etl.load_all --config config.json

Author: Brain Researcher Team
"""

import argparse
import faulthandler
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

# Import unified loaders
from brain_researcher.config import get_repo_root
from brain_researcher.core.ingestion.graph_factory import (
    GraphDatabaseProtocol,
    GraphFactory,
)
from brain_researcher.services.neurokg.graph.graph_factory import create_graph_client
from brain_researcher.core.ingestion.loaders.allen_brain_unified import (
    AllenBrainUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.allen_hba_loader import (
    AllenHBALoader,
    upsert_expression_spine,
)
from brain_researcher.core.ingestion.loaders.bids_unified import BIDSUnifiedLoader
from brain_researcher.core.ingestion.loaders.brainmap_unified import (
    BrainMapUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.cognitive_atlas_unified import (
    CognitiveAtlasUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.neuromaps_unified import (
    NeuromapsUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.neurostore_unified import (
    NeurostoreUnifiedLoader,
    collect_dois_from_record,
)
from brain_researcher.core.ingestion.loaders.neurosynth_unified import (
    NeuroSynthUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.neurovault_unified import (
    NeuroVaultUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.niclip_embeddings import (
    EmbeddingBatch,
    NICLIPEmbeddingLoader,
)
from brain_researcher.core.ingestion.loaders.nilearn_atlas_unified import (
    NilearnAtlasUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.onvoc_unified import OnvocUnifiedLoader
from brain_researcher.core.ingestion.loaders.openneuro_glm_loader import (
    OpenNeuroGLMFitlinsLoader,
)
from brain_researcher.core.ingestion.loaders.openneuro_glm_loader import (
    load_path_config as load_glmfitlins_path_config,
)
from brain_researcher.core.ingestion.loaders.openneuro_onvoc_annotations import (
    OpenNeuroOnvocAnnotationApplier,
    OpenNeuroOnvocAnnotationLoader,
)
from brain_researcher.core.ingestion.loaders.openneuro_study_links import (
    link_openneuro_dataset_studies,
)
from brain_researcher.core.ingestion.loaders.openneuro_unified import (
    OpenNeuroUnifiedLoader,
)
from brain_researcher.core.ingestion.loaders.publication_study_alignment import (
    link_publication_study_alignments,
)
from brain_researcher.core.ingestion.loaders.pubmed_unified import PubMedUnifiedLoader
from brain_researcher.core.ingestion.loaders.virtual_brain_loader import (
    VirtualBrainLoader,
)
from brain_researcher.core.ingestion.loaders.wikidata_unified import (
    WikiDataUnifiedLoader,
)
from brain_researcher.core.ingestion.ondemand import OnDemandRegistry
from brain_researcher.services.neurokg.etl.adapters import (
    AllenHBAAdapter,
    NeuroQueryAdapter,
    NeuroscoutAdapter,
    NiMAREAdapter,
    VirtualBrainAdapter,
)
from brain_researcher.services.neurokg.etl.linkers.neurostore_task_linker import (
    ConstructManager,
    NeurostoreTaskLinker,
)
from brain_researcher.services.neurokg.etl.linkers.taxonomy_linker import (
    TaxonomyLinker,
)
from brain_researcher.services.neurokg.etl.loaders.enhanced_neurovault_loader import (
    EnhancedNeuroVaultLoader,
)
from brain_researcher.services.neurokg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.neurokg.etl.loaders.neurobagel_loader import (
    fetch_neurobagel_data,
    load_neurobagel_data,
)
from brain_researcher.services.neurokg.etl.loaders.neurobagel_public_loader import (
    load_neurobagel_public,
)
from brain_researcher.services.neurokg.etl.loaders.nidm_results_loader import (
    NIDMResultsLoader,
)
from brain_researcher.services.neurokg.etl.loaders.scholarly_metadata_loader import (
    ScholarlyMetadataLoader,
)
from brain_researcher.services.neurokg.spatial.neuromaps_assets import (
    preferred_neuromaps_root,
)
from brain_researcher.services.neurokg.utils.onvoc_linker import OnvocLinker
from brain_researcher.services.neurokg.utils.task_taxonomy import (
    TaskMatchResult,
    TaskTaxonomyResolver,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("data_ingestion.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

if os.getenv("BR_FAULTHANDLER", "").lower() not in {"", "0", "false"}:
    faulthandler.enable()
    try:
        faulthandler.register(signal.SIGUSR1)
    except Exception:
        pass


class MasterDataLoader:
    """Master loader that orchestrates all data ingestion."""

    SOURCE_DEFAULT_MODES = {
        "cognitive_atlas": "full",
        "nilearn_atlases": "full",
        "neurobagel": "full",
        "pubmed": "spine",
        "neurosynth": "spine",
        "neurovault": "spine",
        "openneuro": "spine",
        "openneuro_glmfitlins": "full",
        "wikidata": "spine",
        "niclip": "spine",
        "brainmap": "spine",
        "bids": "spine",
        "neuromaps": "spine",
        "neurostore": "spine",
        "gabriel": "spine",
        "scholarly_metadata": "on_demand",
        "nidm_results": "on_demand",
        "neuroquery": "on_demand",
        "nimare": "on_demand",
        "neuroscout": "on_demand",
        "onvoc": "full",
        "allen_hba": "spine",
        "allen_ccfv3": "spine",
        "virtual_brain": "spine",
    }

    def __init__(
        self,
        db: GraphDatabaseProtocol | None = None,
        *,
        db_factory: GraphFactory | None = None,
        db_path: str | None = None,
    ):
        """
        Initialize the master data loader.

        Args:
            db: Optional pre-configured graph database connection.
            db_factory: Callable returning a graph database connection. Used when
                ``db`` is not supplied.
            db_path: Optional local path used for auxiliary caches (for example,
                BIDS validation results). This does not configure the graph DB.
        """
        default_db_path = db_path or os.getenv(
            "NEUROKG_INGEST_CACHE_PATH", "data/neurokg/cache/ingestion_cache.db"
        )
        # Normalize to absolute path to avoid issues if working directory changes
        self.db_path = str(Path(default_db_path).resolve())
        self.db: GraphDatabaseProtocol | None = db
        self.db_factory = db_factory
        self.ondemand = OnDemandRegistry()
        self.stats = {
            "start_time": datetime.now(),
            "sources_loaded": [],
            "total_entities": 0,
            "total_relationships": 0,
            "errors": [],
        }
        self.run_id = uuid.uuid4().hex
        self.stats["run_id"] = self.run_id

        # Coordinate generation configuration
        self.coordinate_rounding_mm = 1
        self._init_database()
        self._taxonomy_linker: TaxonomyLinker | None | bool = None

    def _default_mode_for(self, source: str) -> str:
        return self.SOURCE_DEFAULT_MODES.get(source, "spine")

    @staticmethod
    def _filter_fields(data: Dict[str, Any], allowed: Iterable[str]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in data.items()
            if key in allowed and value not in (None, "", [], {})
        }

    @staticmethod
    def _collect_dois(record: Dict[str, Any]) -> Set[str]:
        """Extract DOI strings from a publication-like record."""
        return collect_dois_from_record(record)

    def _get_taxonomy_linker(self) -> Optional[TaxonomyLinker]:
        linker = getattr(self, "_taxonomy_linker", None)
        if linker is False:
            return None
        if linker is None:
            try:
                linker = TaxonomyLinker()
                self._taxonomy_linker = linker
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Taxonomy linker unavailable: %s", exc)
                self._taxonomy_linker = False
                return None
        return linker

    def _compute_config_hash(self, config: Dict[str, Any]) -> str:
        payload = json.dumps(config, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _resolve_git_sha(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=get_repo_root(),
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except Exception:
            return None

    def _get_latest_map_index(self, map_index_dir: Path) -> Optional[Path]:
        try:
            if not map_index_dir.exists():
                return None
            candidates = list(map_index_dir.glob("neurovault_map_index_*.jsonl"))
            if not candidates:
                return None
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        except Exception:
            return None

    def _record_ingestion_run(
        self,
        *,
        results: Dict[str, Any],
        config: Dict[str, Any],
        sources: Iterable[str],
    ) -> None:
        if not self.db or not hasattr(self.db, "create_node"):
            return
        try:
            start_time = self.stats.get("start_time")
            end_time = self.stats.get("end_time")
            duration_sec = None
            if start_time and end_time:
                duration_sec = (end_time - start_time).total_seconds()

            run_id = getattr(self, "run_id", uuid.uuid4().hex)
            payload = {
                "id": run_id,
                "run_id": run_id,
                "started_at": start_time.isoformat() if start_time else None,
                "finished_at": end_time.isoformat() if end_time else None,
                "duration_sec": duration_sec,
                "sources": list(sources),
                "config_hash": self._compute_config_hash(config),
                "git_sha": self._resolve_git_sha(),
                "db_uri": os.getenv("NEO4J_URI"),
                "db_name": os.getenv("NEO4J_DATABASE"),
                "total_entities": self.stats.get("total_entities"),
                "total_relationships": self.stats.get("total_relationships"),
                "errors": self.stats.get("errors", []),
            }
            neurovault_result = results.get("neurovault", {}).get("result")
            if neurovault_result:
                payload["neurovault_summary"] = neurovault_result

            self.db.create_node("IngestionRun", payload, node_id=run_id)
            logger.info("Recorded ingestion run metadata (run_id=%s)", run_id)
        except Exception as exc:
            logger.warning("Failed to record ingestion run metadata: %s", exc)

    def _register_on_demand_source(
        self, source: str, cfg: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        ttl = cfg.get("cache_ttl_sec")

        if source == "scholarly_metadata":
            loader = ScholarlyMetadataLoader(
                cache_dir=cfg.get("cache_dir"),
                http_timeout=cfg.get("http_timeout", 20),
                crossref_mailto=cfg.get("crossref_mailto"),
            )
            adapter = loader.make_adapter(cfg)
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        if source == "nidm_results":
            loader = NIDMResultsLoader(
                cache_dir=cfg.get("cache_dir"),
                http_timeout=cfg.get("http_timeout", 30),
            )
            adapter = loader.make_adapter(cfg)
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        if source == "neuroquery":
            adapter = NeuroQueryAdapter(data_path=cfg.get("data_path"))
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        if source == "nimare":
            adapter = NiMAREAdapter(data_path=cfg.get("data_path"))
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        if source == "neuroscout":
            adapter = NeuroscoutAdapter(data_path=cfg.get("data_path"))
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        if source == "allen_hba":
            adapter = AllenHBAAdapter(data_path=cfg.get("data_path"))
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        if source == "virtual_brain":
            cache_dir = cfg.get("cache_dir", "data/virtual_brain/cache")
            adapter = VirtualBrainAdapter(cache_dir=cache_dir)
            self.ondemand.register(source, adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        logger.warning(
            "Source %s configured as on-demand but no adapter available", source
        )
        return {"mode": "on_demand", "registered": False}

    def _init_database(self):
        """Initialize the database connection."""
        if self.db is not None:
            logger.info(
                "Using provided graph database connection (%s)",
                type(self.db).__name__,
            )
            return

        factory = self.db_factory or (lambda: create_graph_client())

        try:
            self.db = factory()
            logger.info(
                "Connected to graph database backend: %s", type(self.db).__name__
            )
            self._create_indexes()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(f"Failed to initialize database: {exc}")
            raise

    def _create_indexes(self):
        """Create database indexes for better performance."""
        indexes = [
            ("Concept", "name"),
            ("Concept", "id"),
            ("Task", "name"),
            ("Task", "id"),
            ("BrainRegion", "name"),
            ("Study", "pmid"),
            ("Study", "doi"),
            ("Dataset", "accession"),
        ]

        if not hasattr(self.db, "create_index"):
            logger.debug(
                "Skipping index creation; backend %s does not support create_index",
                type(self.db).__name__,
            )
            return

        for label, property_name in indexes:
            try:
                self.db.create_index(label, property_name)
                logger.debug(f"Created index on {label}.{property_name}")
            except Exception:
                # Index might already exist or backend may not support the call
                logger.debug(
                    "Index creation skipped for %s.%s on backend %s",
                    label,
                    property_name,
                    type(self.db).__name__,
                )

    @staticmethod
    def _sanitize_id_segment(value: str) -> str:
        if value is None:
            return "unknown"
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", str(value).strip().lower())
        cleaned = cleaned.strip("-")
        return cleaned or "unknown"

    @staticmethod
    def _split_aliases(value: str | None) -> List[str]:
        if not value:
            return []
        text = str(value)
        for sep in [";", ",", "|", "/"]:
            text = text.replace(sep, "|")
        return [token.strip() for token in text.split("|") if token.strip()]

    @staticmethod
    def _serialize_for_json(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {
                str(key): MasterDataLoader._serialize_for_json(val)
                for key, val in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [MasterDataLoader._serialize_for_json(item) for item in value]
        return str(value)

    @staticmethod
    def _is_primitive(value: Any) -> bool:
        return value is None or isinstance(value, (str, int, float, bool))

    @classmethod
    def _flatten_value(cls, value: Any) -> Any:
        if cls._is_primitive(value):
            return value
        if isinstance(value, (list, tuple, set)):
            flattened: List[Any] = []
            for item in value:
                if cls._is_primitive(item):
                    flattened.append(item)
                else:
                    flattened.append(
                        json.dumps(
                            cls._serialize_for_json(item),
                            sort_keys=True,
                            default=str,
                        )
                    )
            return flattened
        if isinstance(value, dict):
            return json.dumps(
                cls._serialize_for_json(value),
                sort_keys=True,
                default=str,
            )
        return str(value)

    @classmethod
    def _flatten_properties(cls, properties: Dict[str, Any]) -> Dict[str, Any]:
        return {key: cls._flatten_value(value) for key, value in properties.items()}

    def _ensure_scholarly_metadata(
        self,
        dois: Iterable[str],
        config: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        dois_normalized = {
            (doi or "").strip().lower().replace("https://doi.org/", "")
            for doi in dois
            if doi
        }
        dois_normalized.discard("")
        if not dois_normalized:
            return None

        missing: List[str] = []
        for doi in dois_normalized:
            matches = self.db.find_nodes("Publication", {"doi": doi})
            if not matches:
                missing.append(doi)

        if not missing:
            logger.debug(
                "All %d DOIs already present; skipping scholarly harvest",
                len(dois_normalized),
            )
            return None

        loader = ScholarlyMetadataLoader(
            cache_dir=config.get("cache_dir"),
            http_timeout=config.get("http_timeout", 20),
            crossref_mailto=config.get("crossref_mailto"),
        )
        try:
            stats = loader.ingest(self.db, dois=missing)
            logger.info(
                "Fetched metadata for %d/%d missing DOIs",
                stats["publications_upserted"],
                len(missing),
            )
            return stats
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Scholarly metadata harvest failed: %s", exc, exc_info=True)
            return {"error": str(exc), "requested_dois": missing}

    def _create_relationship_safe(
        self,
        start: Optional[str],
        end: Optional[str],
        rel_type: Optional[str],
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Create relationship if it does not already exist."""
        if not start or not end or not rel_type:
            return False
        existing = self.db.find_relationships(
            start_node=start, end_node=end, rel_type=rel_type
        )
        if existing:
            return False
        props = self._flatten_properties(dict(properties or {}))
        try:
            return bool(self.db.create_relationship(start, end, rel_type, props))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Skipping relationship %s -[%s]-> %s due to error: %s",
                start,
                rel_type,
                end,
                exc,
            )
            return False

    def _link_neurostore_metadata(self, link_tasks: bool = True) -> Dict[str, int]:
        """Link Neurostore tasks to Cognitive Atlas concepts, domains, and tasks."""
        concept_links = 0
        domain_links = 0
        mapsto_links = 0

        neurostore_tasks = [
            (node_id, data)
            for node_id, data in self.db.find_nodes("Task")
            if data.get("source") == "neurostore"
        ]
        if not neurostore_tasks:
            return {"concept_links": 0, "domain_links": 0, "mapsto_links": 0}

        concept_name_to_id: Dict[str, str] = {}
        for concept_id, data in self.db.find_nodes("Concept", {}):
            name = (data.get("name") or "").strip()
            if name:
                concept_name_to_id.setdefault(name.lower(), concept_id)
            alias_field = data.get("alias") or ""
            if alias_field:
                for alias in self._split_aliases(alias_field):
                    if alias:
                        concept_name_to_id.setdefault(alias.strip().lower(), concept_id)
            for alias in data.get("aliases", []) or []:
                if alias:
                    concept_name_to_id.setdefault(alias.strip().lower(), concept_id)

        class_lookup: Dict[str, str] = {}
        for class_id, data in self.db.find_nodes("ConceptClass", {}):
            name = (data.get("name") or "").strip()
            if name:
                class_lookup.setdefault(name.lower(), class_id)
            description = (data.get("description") or "").strip()
            if description:
                class_lookup.setdefault(description.lower(), class_id)

        for node_id, data in neurostore_tasks:
            for concept_label in data.get("concepts_normalized", []) or []:
                concept_id = concept_name_to_id.get(concept_label.strip().lower())
                if concept_id and self._create_relationship_safe(
                    node_id,
                    concept_id,
                    "ASSERTS",
                    {"source": "neurostore"},
                ):
                    concept_links += 1

            for domain_label in data.get("domains_normalized", []) or []:
                class_id = class_lookup.get(domain_label.strip().lower())
                if class_id and self._create_relationship_safe(
                    node_id,
                    class_id,
                    "HAS_DOMAIN",
                    {"source": "neurostore"},
                ):
                    domain_links += 1

        if link_tasks:
            try:
                from brain_researcher.services.neurokg.utils.node_label_linker import (
                    NodeLabelLinker,
                )

                linker = NodeLabelLinker(self.db)
                cogatlas_tasks = [
                    (node_id, data)
                    for node_id, data in self.db.find_nodes("Task")
                    if data.get("source") == "cognitive_atlas_niclip"
                ]
                if cogatlas_tasks:
                    matches = linker.match_nodes(
                        neurostore_tasks,
                        cogatlas_tasks,
                        embed_threshold=0.82,
                        fuzzy_threshold=82,
                    )
                    for source_id, target_id, score, method in matches:
                        if self._create_relationship_safe(
                            source_id,
                            target_id,
                            "MAPS_TO",
                            {
                                "source": "neurostore_niclip",
                                "confidence": round(score, 4),
                                "method": method,
                                "embedding_model": linker.last_embedding_model,
                            },
                        ):
                            mapsto_links += 1
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Failed to link Neurostore tasks via embeddings: %s", exc
                )

        return {
            "concept_links": concept_links,
            "domain_links": domain_links,
            "mapsto_links": mapsto_links,
        }

    def _generate_coordinate_id(
        self,
        coord: Dict[str, Any],
        origin_hint: Optional[str] = None,
    ) -> str:
        try:
            x_val = float(coord.get("x"))
            y_val = float(coord.get("y"))
            z_val = float(coord.get("z"))
        except (TypeError, ValueError):
            raise ValueError("Coordinate missing numeric x/y/z values")

        precision = max(1, int(self.coordinate_rounding_mm))
        round_axis = lambda val: int(round(val / precision) * precision)

        round_x = round_axis(x_val)
        round_y = round_axis(y_val)
        round_z = round_axis(z_val)

        space = coord.get("space") or coord.get("atlas") or "unknown"
        space_segment = self._sanitize_id_segment(space)

        origin_candidates = [
            origin_hint,
            coord.get("study_id"),
            coord.get("dataset_id"),
            coord.get("dataset"),
            coord.get("collection_id"),
            coord.get("experiment_id"),
            coord.get("paper_id"),
            coord.get("source_file"),
        ]
        origin = next(
            (str(item) for item in origin_candidates if item not in (None, "")),
            "unknown",
        )
        origin_segment = self._sanitize_id_segment(origin)

        coord_id = f"coord:{space_segment}:{precision}mm:{round_x}:{round_y}:{round_z}:{origin_segment}"

        coord.setdefault("space", space)
        coord["rounding_mm"] = precision
        return coord_id

    # ------------------------------------------------------------------
    # Coordinate resume helpers
    # ------------------------------------------------------------------
    def _count_existing_coordinates(self, source: str) -> int:
        """Return existing Coordinate node count for a given source."""

        # Prefer lightweight COUNT(*) if the backend supports Cypher
        run_cypher = getattr(self.db, "_run", None)
        if callable(run_cypher):
            try:
                record = run_cypher(
                    "MATCH (:Coordinate {source:$source}) RETURN count(*) AS cnt",
                    {"source": source},
                ).single()
                if record and record.get("cnt") is not None:
                    return int(record["cnt"])
            except Exception as exc:  # pragma: no cover - diagnostic only
                logger.debug("Cypher count for %s coordinates failed: %s", source, exc)

        # Fallback: try find_nodes (can be expensive on Neo4j)
        find_nodes = getattr(self.db, "find_nodes", None)
        if callable(find_nodes):
            try:
                return len(find_nodes("Coordinate", {"source": source}))
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "find_nodes count for %s coordinates failed: %s", source, exc
                )

        # Final fallback: inspect the in-memory graph cache if available
        graph = getattr(self.db, "graph", None)
        if graph is not None:
            try:
                return sum(
                    1
                    for _, data in graph.nodes(data=True)
                    if data.get("source") == source
                    and "Coordinate" in self._normalize_labels(data)
                )
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "Graph cache count for %s coordinates failed: %s", source, exc
                )

        return 0

    @staticmethod
    def _normalize_labels(node_props: Dict[str, Any]) -> List[str]:
        labels = node_props.get("labels")
        if labels is None:
            return []
        if isinstance(labels, str):
            return [labels]
        if isinstance(labels, list):
            return labels
        return []

    def _determine_coordinate_resume_offset(
        self,
        *,
        source: str,
        total_coordinates: int,
        config: Dict[str, Any],
        env_var: str = "NEUROKG_COORDINATE_RESUME_OFFSET",
    ) -> int:
        """Determine resume offset via env/config/auto-detect."""

        # Explicit env override takes precedence
        env_value = os.getenv(env_var)
        if env_value:
            try:
                offset = max(0, int(env_value))
                return min(offset, total_coordinates)
            except ValueError:
                logger.warning(
                    "%s is not an integer (got %r); ignoring resume override",
                    env_var,
                    env_value,
                )

        cfg_value = config.get("resume_coordinate_offset")
        if cfg_value is not None:
            try:
                offset = max(0, int(cfg_value))
                return min(offset, total_coordinates)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid resume_coordinate_offset=%r in config; ignoring",
                    cfg_value,
                )

        existing = self._count_existing_coordinates(source)
        if existing:
            return min(existing, total_coordinates)
        return 0

    def load_cognitive_atlas(
        self, config: Dict[str, Any] = None, mode: str = "full"
    ) -> Dict[str, int]:
        """
        Load Cognitive Atlas data.

        Args:
            config: Configuration dictionary

        Returns:
            Statistics about loaded data
        """
        logger.info("Loading Cognitive Atlas data...")
        config = config or {}
        mode = (config.get("mode") or mode or "full").lower()

        try:
            # Use unified loader with NICLIP data
            loader = CognitiveAtlasUnifiedLoader(
                use_niclip_data=config.get("use_niclip", True),
                niclip_path=config.get("niclip_path"),
                data_dir=config.get("data_dir"),
                use_ca_assertions=config.get("use_ca_assertions", True),
                ca_dump_path=config.get("ca_dump_path"),
            )

            # Load data
            concepts = loader.load_concepts()
            tasks = loader.load_tasks()
            mappings = loader.load_mappings()

            # Insert into database
            concept_count = 0
            task_count = 0
            mapping_count = 0
            dois_for_metadata: Set[str] = set()

            # Insert concepts (handle duplicates)
            for concept in concepts:
                try:
                    concept_payload = self._flatten_properties(dict(concept))
                    node_id = self.db.create_node("Concept", concept_payload)
                    if node_id:
                        concept_count += 1
                except Exception as e:
                    if "already exists" in str(e):
                        logger.debug(
                            f"Concept {concept.get('id')} already exists, skipping"
                        )
                    else:
                        logger.warning(
                            f"Failed to insert concept {concept.get('id')}: {e}"
                        )

            # Insert tasks (handle duplicates)
            for task in tasks:
                try:
                    task_payload = self._flatten_properties(dict(task))
                    node_id = self.db.create_node("Task", task_payload)
                    if node_id:
                        task_count += 1
                except Exception as e:
                    if "already exists" in str(e):
                        logger.debug(f"Task {task.get('id')} already exists, skipping")
                    else:
                        logger.warning(f"Failed to insert task {task.get('id')}: {e}")

            concept_lookup = {
                concept["id"]: concept for concept in concepts if concept.get("id")
            }
            task_lookup = {task["id"]: task for task in tasks if task.get("id")}

            # Concept class nodes and relationships
            for concept_id, concept_data in concept_lookup.items():
                for class_info in concept_data.get("concept_classes", []) or []:
                    class_id = (
                        class_info.get("id")
                        or f"class:{self._sanitize_id_segment(class_info.get('name'))}"
                    )
                    if not class_id:
                        continue
                    class_props = dict(class_info)
                    class_props["id"] = class_id
                    class_props["source"] = "cognitive_atlas"
                    class_payload = self._flatten_properties(class_props)
                    self.db.create_node(
                        ["Process", "ConceptClass"], class_payload, node_id=class_id
                    )
                    rel_type = class_info.get("relationship", "CLASSIFIED_UNDER")
                    properties = {"source": "cognitive_atlas"}
                    self._create_relationship_safe(
                        concept_id, class_id, rel_type or "CLASSIFIED_UNDER", properties
                    )

                # Concept-level citations
                for citation in concept_data.get("citations", []) or []:
                    citation_id = citation.get("id")
                    if not citation_id:
                        continue
                    citation_props = dict(citation)
                    citation_props["id"] = citation_id
                    citation_props["source"] = "cognitive_atlas"
                    if citation.get("doi"):
                        dois_for_metadata.add(str(citation["doi"]))
                    citation_payload = self._flatten_properties(citation_props)
                    self.db.create_node(
                        "Citation", citation_payload, node_id=citation_id
                    )
                    rel_type = citation.get("relationship", "HAS_CITATION")
                    properties = {"source": "cognitive_atlas"}
                    self._create_relationship_safe(
                        concept_id, citation_id, rel_type or "HAS_CITATION", properties
                    )

                # Concept relationships to other concepts
                for relation in concept_data.get("related_concepts", []) or []:
                    target_id = relation.get("id") or relation.get("concept_id")
                    if not target_id or target_id == concept_id:
                        continue
                    if target_id not in concept_lookup and not self.db.find_nodes(
                        "Concept", {"id": target_id}
                    ):
                        continue
                    rel_type = (relation.get("relationship") or "RELATED_TO").upper()
                    direction = (relation.get("direction") or "").lower()
                    if direction == "child":
                        start_node, end_node = target_id, concept_id
                    elif direction == "parent":
                        start_node, end_node = concept_id, target_id
                    else:
                        start_node, end_node = concept_id, target_id
                    properties = {"source": "cognitive_atlas"}
                    if relation.get("definition_text"):
                        properties["definition_text"] = relation["definition_text"]
                    if relation.get("alias"):
                        properties["alias"] = relation["alias"]
                    self._create_relationship_safe(
                        start_node, end_node, rel_type, properties
                    )

                # Concept links to tasks/contrasts
                for link in concept_data.get("contrast_links", []) or []:
                    task_id = link.get("task_id")
                    if not task_id:
                        continue
                    if task_id not in task_lookup and not self.db.find_nodes(
                        "Task", {"id": task_id}
                    ):
                        continue
                    rel_type = (link.get("relationship") or "MEASUREDBY").upper()
                    properties = {
                        "source": "cognitive_atlas",
                        "contrast_id": link.get("id"),
                        "name": link.get("name"),
                    }
                    self._create_relationship_safe(
                        concept_id, task_id, rel_type, properties
                    )

            # Task enrichments: concept assertions, conditions, indicators, contrasts, batteries, citations
            for task_id, task_data in task_lookup.items():
                # Task-to-concept relationships
                for relation in task_data.get("concept_relations", []) or []:
                    concept_id = relation.get("concept_id") or relation.get("id")
                    if not concept_id:
                        continue
                    if concept_id not in concept_lookup and not self.db.find_nodes(
                        "Concept", {"id": concept_id}
                    ):
                        continue
                    rel_type = (relation.get("relationship") or "RELATED_TO").upper()
                    properties = {"source": "cognitive_atlas"}
                    if relation.get("contrasts"):
                        properties["contrasts"] = relation["contrasts"]
                    self._create_relationship_safe(
                        task_id, concept_id, rel_type, properties
                    )

                if mode == "full":
                    # Task conditions
                    for idx, condition in enumerate(
                        task_data.get("conditions", []) or []
                    ):
                        condition_id = (
                            condition.get("id") or f"{task_id}:condition:{idx}"
                        )
                        if not condition_id:
                            continue
                        condition_props = dict(condition)
                        condition_props["id"] = condition_id
                        condition_props["task_id"] = task_id
                        condition_props["source"] = "cognitive_atlas"
                        condition_payload = self._flatten_properties(condition_props)
                        self.db.create_node(
                            "TaskCondition", condition_payload, node_id=condition_id
                        )
                        rel_type = condition.get("relationship", "HASCONDITION")
                        self._create_relationship_safe(
                            task_id,
                            condition_id,
                            rel_type or "HASCONDITION",
                            {"source": "cognitive_atlas"},
                        )

                    # Task indicators
                    for idx, indicator in enumerate(
                        task_data.get("indicators", []) or []
                    ):
                        indicator_id = indicator.get("id")
                        if not indicator_id:
                            slug = self._sanitize_id_segment(
                                indicator.get("type") or f"indicator-{idx}"
                            )
                            indicator_id = f"{task_id}:indicator:{slug}"
                        indicator_props = dict(indicator)
                        indicator_props["id"] = indicator_id
                        indicator_props["task_id"] = task_id
                        indicator_props["source"] = "cognitive_atlas"
                        indicator_payload = self._flatten_properties(indicator_props)
                        self.db.create_node(
                            "TaskIndicator", indicator_payload, node_id=indicator_id
                        )
                        rel_type = indicator.get("relationship", "HASINDICATOR")
                        self._create_relationship_safe(
                            task_id,
                            indicator_id,
                            rel_type or "HASINDICATOR",
                            {"source": "cognitive_atlas"},
                        )

                    # Task citations
                    for citation in task_data.get("citations", []) or []:
                        citation_id = citation.get("id")
                        if not citation_id:
                            continue
                        citation_props = dict(citation)
                        citation_props["id"] = citation_id
                        citation_props["source"] = "cognitive_atlas"
                        if citation.get("doi"):
                            dois_for_metadata.add(str(citation["doi"]))
                        citation_payload = self._flatten_properties(citation_props)
                        self.db.create_node(
                            "Citation", citation_payload, node_id=citation_id
                        )
                        rel_type = citation.get("relationship", "HAS_CITATION")
                        self._create_relationship_safe(
                            task_id,
                            citation_id,
                            rel_type or "HAS_CITATION",
                            {"source": "cognitive_atlas"},
                        )

                    # Task contrasts
                    for contrast in task_data.get("contrasts", []) or []:
                        contrast_id = contrast.get("id")
                        if not contrast_id:
                            continue
                        contrast_props = dict(contrast)
                        contrast_props["id"] = contrast_id
                        contrast_props["task_id"] = task_id
                        contrast_props["source"] = "cognitive_atlas"
                        contrast_payload = self._flatten_properties(contrast_props)
                        self.db.create_node(
                            "Contrast", contrast_payload, node_id=contrast_id
                        )
                        self._create_relationship_safe(
                            task_id,
                            contrast_id,
                            "HAS_CONTRAST",
                            {"source": "cognitive_atlas"},
                        )

                    # Task batteries
                    for battery in task_data.get("batteries", []) or []:
                        battery_id = battery.get("id")
                        if not battery_id:
                            continue
                        battery_props = dict(battery)
                        battery_props["id"] = battery_id
                        battery_props["source"] = "cognitive_atlas"
                        battery_payload = self._flatten_properties(battery_props)
                        self.db.create_node(
                            "Battery", battery_payload, node_id=battery_id
                        )
                        rel_type = battery.get("relationship", "INBATTERY")
                        self._create_relationship_safe(
                            task_id,
                            battery_id,
                            rel_type or "INBATTERY",
                            {"source": "cognitive_atlas"},
                        )

            # Create relationships from mappings (Task -> Concept)
            removed_measures = self.db.delete_relationships("MEASURES")
            if removed_measures:
                logger.info(
                    "Removed %d existing MEASURES relationships", removed_measures
                )
            existing_measures = {
                (start, end)
                for start, end, _ in self.db.find_relationships(rel_type="MEASURES")
            }
            concept_task_map = mappings.get("concept_to_task", {})
            metadata_lookup = mappings.get("task_concept_metadata", {})

            for concept_id, task_values in concept_task_map.items():
                if not concept_id or not task_values:
                    continue

                if isinstance(task_values, str):
                    task_iter = [task_values]
                elif isinstance(task_values, (list, tuple, set)):
                    task_iter = [str(item) for item in task_values if item]
                else:
                    task_iter = [str(task_values)]

                for task_id in task_iter:
                    if not task_id:
                        continue
                    pair = (task_id, concept_id)
                    if pair in existing_measures:
                        continue

                    props = {"source": "cognitive_atlas"}
                    meta_key = f"{task_id}::{concept_id}"
                    if meta_key in metadata_lookup:
                        props.update(metadata_lookup[meta_key])
                    rel_id = self.db.create_relationship(
                        task_id,
                        concept_id,
                        "MEASURES",
                        self._flatten_properties(props),
                    )
                    if rel_id:
                        mapping_count += 1
                        existing_measures.add(pair)

            total_measures = len(self.db.find_relationships(rel_type="MEASURES"))
            if concept_count <= 500 or total_measures < 2000:
                raise ValueError(
                    f"Cognitive Atlas load incomplete: concepts={concept_count}, MEASURES={total_measures}"
                )

            stats = {
                "concepts": concept_count,
                "tasks": task_count,
                "mappings": mapping_count,
            }

            auto_meta_cfg = config.get("auto_scholarly_metadata", {})
            if auto_meta_cfg.get("enabled", True):
                meta_stats = self._ensure_scholarly_metadata(
                    dois_for_metadata, auto_meta_cfg
                )
                if meta_stats:
                    stats["scholarly_metadata"] = meta_stats

            logger.info(f"Loaded Cognitive Atlas: {stats}")
            self.stats["sources_loaded"].append("cognitive_atlas")
            return stats

        except Exception as e:
            logger.error(f"Failed to load Cognitive Atlas: {e}")
            self.stats["errors"].append(f"cognitive_atlas: {e}")
            return {"error": str(e)}

    def load_onvoc(
        self, config: Dict[str, Any] = None, mode: str = "full"
    ) -> Dict[str, int]:
        """Load the OpenNeuro Vocabulary (ONVOC) into the knowledge graph."""

        logger.info("Loading ONVOC vocabulary...")
        config = config or {}
        data_dir = config.get("data_dir") or "data/ontologies/onvoc"

        loader = OnvocUnifiedLoader(data_dir=data_dir)

        try:
            concepts = loader.load_concepts()
            relationships = loader.load_relationships()
        except FileNotFoundError as exc:
            logger.warning("ONVOC artifacts missing: %s", exc)
            return {"skipped": True, "reason": "missing-artifacts"}

        stats = {
            "concepts": len(concepts),
            "relationships": len(relationships),
            "created_concepts": 0,
            "created_relationships": 0,
        }

        if not self.db:
            logger.warning(
                "No database connection available; skipping ONVOC graph writes."
            )
            self.stats["sources_loaded"].append("onvoc")
            return stats

        for concept in concepts:
            node_id = concept.get("id")
            if not node_id:
                continue
            properties = {
                "name": concept.get("label") or node_id,
                "label": concept.get("label") or node_id,
                "source": "onvoc",
                "scheme": concept.get("scheme", "ONVOC"),
                "uri": concept.get("uri"),
                "definition": concept.get("definition"),
                "synonyms": concept.get("synonyms") or [],
                "is_top_concept": bool(concept.get("is_top_concept")),
                "top_schemes": concept.get("top_of") or [],
            }
            try:
                self.db.create_node(
                    ["Concept", "OntologyConcept", "OnvocClass"],
                    properties,
                    node_id=node_id,
                )
                stats["created_concepts"] += 1
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Skipping ONVOC concept %s due to error: %s", node_id, exc)

        for rel in relationships:
            child = rel.get("child_id")
            parent = rel.get("parent_id")
            if not child or not parent or child == parent:
                continue
            rel_type = rel.get("edge_type") or "CLASSIFIED_UNDER"
            props = {
                "source": "onvoc",
                "scheme": "ONVOC",
                "relation": rel.get("relation"),
            }
            if self._create_relationship_safe(child, parent, rel_type, props):
                stats["created_relationships"] += 1

        self.stats["sources_loaded"].append("onvoc")
        return stats

    def load_pubmed(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load PubMed literature data with NICLIP embeddings.

        Args:
            config: Configuration dictionary

        Returns:
            Statistics about loaded data
        """
        logger.info("Loading PubMed data...")
        config = config or {}
        mode = (mode or "spine").lower()

        try:
            # Use unified PubMed loader
            loader = PubMedUnifiedLoader(
                use_niclip=config.get("use_niclip", True),
                niclip_path=config.get("niclip_path"),
                cache_dir=config.get("cache_dir"),
                api_key=config.get("api_key"),
            )

            # Search and load articles
            search_query = config.get("search_query", "fMRI neuroimaging")
            max_results = config.get("max_results", 1000)

            articles = loader.load_publications(query=search_query, limit=max_results)

            # Insert into database
            article_count = 0
            coordinate_count = 0

            spine_fields = {"pmid", "doi", "title", "year", "journal", "source"}

            for article in articles:
                coordinates = article.get("coordinates")
                article_data = dict(article)
                article_data.setdefault("source", "pubmed")
                if mode == "spine":
                    article_data = self._filter_fields(article_data, spine_fields)

                article_payload = self._flatten_properties(article_data)
                node_id = self.db.create_node("Publication", article_payload)
                if node_id:
                    article_count += 1
                    # Count coordinates if present
                    if coordinates:
                        coordinate_count += len(coordinates)

            stats = {"publications": article_count, "coordinates": coordinate_count}

            logger.info(f"Loaded PubMed: {stats}")
            self.stats["sources_loaded"].append("pubmed")
            return stats

        except Exception as e:
            logger.error(f"Failed to load PubMed: {e}")
            self.stats["errors"].append(f"pubmed: {e}")
            return {"error": str(e)}

    def load_gabriel(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """Load GABRIEL-derived paper measurements into BR-KG."""

        config = config or {}
        if mode == "on_demand":
            registration = self._register_on_demand_source("gabriel", config)
            return registration or {"mode": "on_demand", "registered": False}

        logger.info("Loading GABRIEL measurements in %s mode...", mode)

        try:
            loader = GabrielMeasurementLoader(self.db, config=config)
            stats = loader.load(mode=mode)
            self.stats["sources_loaded"].append("gabriel")
            logger.info("Loaded GABRIEL measurements: %s", stats)
            return stats
        except Exception as exc:
            logger.error("Failed to load GABRIEL measurements: %s", exc)
            self.stats["errors"].append(f"gabriel: {exc}")
            return {"error": str(exc)}

    def load_neurosynth(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load NeuroSynth meta-analysis data with NICLIP models.

        Args:
            config: Configuration dictionary

        Returns:
            Statistics about loaded data
        """
        logger.info("Loading NeuroSynth data...")
        config = config or {}
        mode = (mode or "spine").lower()

        try:
            # Use unified NeuroSynth loader
            niclip_mode: Optional[str] = None
            use_niclip_value = config.get("use_niclip")
            if isinstance(use_niclip_value, str):
                normalized = use_niclip_value.strip().lower()
                if normalized in {"on_demand", "ondemand"}:
                    niclip_mode = "on_demand"
                    use_niclip_models = False
                elif normalized in {"true", "1", "yes", "persist"}:
                    use_niclip_models = True
                elif normalized in {"false", "0", "no", "off"}:
                    use_niclip_models = False
                else:
                    use_niclip_models = config.get("use_niclip_models", True)
            elif use_niclip_value is None:
                use_niclip_models = config.get("use_niclip_models", True)
            else:
                use_niclip_models = bool(use_niclip_value)

            if niclip_mode == "on_demand" and use_niclip_models:
                # Guard against conflicting configuration
                logger.warning(
                    "NICLIP mode on_demand overrides use_niclip_models=True; disabling NICLIP ingestion"
                )
                use_niclip_models = False

            loader = NeuroSynthUnifiedLoader(
                use_niclip_models=use_niclip_models,
                data_path=config.get("data_path"),
                niclip_path=config.get("niclip_path"),
                model_name=config.get("model_name", "BrainGPT-7B-v0.2"),
                section=config.get("section", "abstract"),
                clip_model_path=config.get("clip_model_path"),
            )

            load_coordinates = bool(config.get("load_coordinates", False))
            load_features = bool(config.get("load_features", False))

            # Load data (avoid pulling large blobs if disabled)
            data = loader.load_data(
                include_coordinates=load_coordinates,
                include_metadata=True,
                include_features=load_features,
                include_models=use_niclip_models,
            )

            # Get data components
            metadata_df = data.get("metadata", pd.DataFrame())
            coordinates_df = data.get("coordinates", pd.DataFrame())
            vocabulary_list = data.get("vocabulary", [])
            features_matrix = data.get("features", None)

            # Insert into database
            study_count = 0
            coordinate_count = 0
            term_count = 0
            term_relationship_count = 0

            # Insert studies from metadata as Publications (merging with existing if present)
            publication_map = (
                {}
            )  # Map identifier -> Publication node_id for relationship creation
            publication_nodes_in_order: list[str | None] = []

            if not metadata_df.empty:
                metadata_df = metadata_df.reset_index(drop=True)
                publication_fields = {
                    "id",
                    "pmid",
                    "doi",
                    "title",
                    "year",
                    "journal",
                    "authors",
                    "space",
                    "source",
                    "neurosynth_id",
                }

                for _, row in metadata_df.iterrows():
                    pub_node_id: str | None = None
                    raw_identifier = str(row.get("id", "")).strip()
                    if not raw_identifier:
                        publication_nodes_in_order.append(None)
                        continue

                    neurosynth_identifier = f"neurosynth:{raw_identifier}"
                    study_data = {
                        key: value
                        for key, value in row.to_dict().items()
                        if key != "id"
                    }
                    study_data["source"] = "neurosynth"
                    study_data["neurosynth_id"] = neurosynth_identifier

                    pmid = str(study_data.get("pmid") or "").strip() or None
                    doi = str(study_data.get("doi") or "").strip() or None

                    if mode == "spine":
                        study_data = self._filter_fields(study_data, publication_fields)

                    lookup_filters = []
                    if pmid:
                        lookup_filters.append({"pmid": pmid})
                    if doi:
                        lookup_filters.append({"doi": doi})
                    lookup_filters.append({"neurosynth_id": neurosynth_identifier})

                    existing_pubs = []
                    for props in lookup_filters:
                        key, value = next(iter(props.items()))
                        if not value:
                            continue
                        matches = self.db.find_nodes("Publication", props)
                        if matches:
                            existing_pubs = matches
                            break

                    if existing_pubs:
                        pub_id, pub_data = existing_pubs[0]
                        update_data = dict(study_data)
                        update_data.pop("id", None)
                        sanitized_updates = self._flatten_properties(update_data)
                        merged_props = dict(pub_data)
                        merged_props.update(sanitized_updates)
                        self.db._save_node(
                            pub_id,
                            sanitized_updates.get("labels", ["Publication"]),
                            merged_props,
                        )
                        publication_map[neurosynth_identifier] = pub_id
                        publication_map[raw_identifier] = pub_id
                        if pmid:
                            publication_map[pmid] = pub_id
                        pub_node_id = pub_id
                        study_count += 1
                        publication_nodes_in_order.append(pub_node_id)
                        continue

                    create_payload = dict(study_data)
                    if pmid:
                        create_payload.setdefault("pmid", pmid)
                        create_payload.setdefault("id", pmid)
                    elif doi:
                        create_payload.setdefault("id", doi)
                    else:
                        create_payload["id"] = neurosynth_identifier

                    create_payload = self._flatten_properties(create_payload)
                    pub_id = self.db.create_node("Publication", create_payload)
                    if pub_id:
                        publication_map[neurosynth_identifier] = pub_id
                        publication_map[raw_identifier] = pub_id
                        if pmid:
                            publication_map[pmid] = pub_id
                        pub_node_id = pub_id
                        study_count += 1
                    publication_nodes_in_order.append(pub_node_id)

            # Insert coordinates and link to Publications
            relationship_count = 0
            coordinate_fields = {"id", "space", "round_mm", "x", "y", "z", "source"}

            if load_coordinates and not coordinates_df.empty:
                env_batch = os.environ.get("NEUROKG_COORDINATE_BATCH_SIZE")
                batch_size = config.get("neurosynth_coordinate_batch_size", 10000)
                if env_batch:
                    try:
                        batch_size = max(1000, int(env_batch))
                    except ValueError:
                        logger.warning(
                            "Invalid NEUROKG_COORDINATE_BATCH_SIZE=%s; using %s",
                            env_batch,
                            batch_size,
                        )
                total_coordinates = len(coordinates_df)
                coord_source = config.get("coordinate_source", "neurosynth")
                resume_offset = self._determine_coordinate_resume_offset(
                    source=coord_source,
                    total_coordinates=total_coordinates,
                    config=config,
                )
                if resume_offset >= total_coordinates:
                    logger.info(
                        "All NeuroSynth coordinates already ingested (count=%s); skipping",
                        total_coordinates,
                    )
                    prepared_records = []
                else:
                    if resume_offset > 0:
                        logger.info(
                            "Resuming NeuroSynth coordinates at index %s/%s (batch=%s)",
                            resume_offset,
                            total_coordinates,
                            batch_size,
                        )

                for start_idx in range(resume_offset, total_coordinates, batch_size):
                    batch_start = time.perf_counter()
                    end_idx = min(start_idx + batch_size, total_coordinates)
                    batch_df = coordinates_df.iloc[start_idx:end_idx]

                    # Prepare node payloads with deterministic coordinate IDs
                    prepared_records = []
                    for record in batch_df.to_dict(orient="records"):
                        record = dict(record)
                        origin_hint = record.get("study_id") or record.get("pmid")
                        try:
                            coord_id = self._generate_coordinate_id(
                                record, origin_hint=origin_hint
                            )
                        except ValueError:
                            logger.debug(
                                "Skipping coordinate with invalid data: %s", record
                            )
                            continue

                        coord_payload = {
                            "id": coord_id,
                            "space": record.get("space"),
                            "x": record.get("x"),
                            "y": record.get("y"),
                            "z": record.get("z"),
                            "round_mm": record.get("rounding_mm")
                            or self.coordinate_rounding_mm,
                            "source": coord_source,
                        }
                        coord_payload = self._filter_fields(
                            coord_payload, coordinate_fields
                        )
                        prepared_records.append(
                            {
                                "node": coord_payload,
                                "study_id": record.get("study_id")
                                or record.get("pmid"),
                            }
                        )

                    if not prepared_records:
                        continue

                    node_inputs = [
                        ("Coordinate", item["node"]) for item in prepared_records
                    ]

                    # Bulk create coordinate nodes to accelerate inserts
                    node_ids = self.db.bulk_create_nodes(
                        node_inputs, batch_size=batch_size
                    )
                    batch_coord_created = len(node_ids)
                    coordinate_count += batch_coord_created

                    # Create relationships for the batch
                    batch_rel_created = 0
                    for coord_id, item in zip(node_ids, prepared_records):
                        study_id = item.get("study_id")
                        if not study_id:
                            continue

                        pub_id = publication_map.get(str(study_id))

                        if not pub_id:
                            pubs = self.db.find_nodes(
                                "Publication", {"pmid": str(study_id)}
                            )
                            if pubs:
                                pub_id, _ = pubs[0]

                        if pub_id:
                            rel_id = self.db.create_relationship(
                                pub_id,
                                coord_id,
                                "HAS_COORDINATE",
                                {"source": "neurosynth_v7"},
                                auto_commit=False,
                            )
                            if rel_id:
                                relationship_count += 1
                                batch_rel_created += 1

                    # Commit relationships for this batch
                    self.db.commit()
                    logger.info(
                        "Committed NeuroSynth coordinate batch %s/%s (coords=%s, rels=%s, batch=%s, %.2fs)",
                        end_idx,
                        total_coordinates,
                        batch_coord_created,
                        batch_rel_created,
                        batch_size,
                        time.perf_counter() - batch_start,
                    )
            elif not load_coordinates:
                logger.info("Skipping NeuroSynth coordinates (load_coordinates=False)")

            # Insert vocabulary terms
            term_node_map: dict[int, str] = {}
            if vocabulary_list:
                existing_terms = self.db.find_nodes("Term", {"source": "neurosynth"})
                term_node_id_by_name: dict[str, str] = {}
                for node_id, props in existing_terms:
                    name = (props or {}).get("name")
                    if name:
                        term_node_id_by_name[str(name)] = node_id

                logger.info(
                    "Ensuring %s NeuroSynth vocabulary terms", len(vocabulary_list)
                )
                for term_idx, term in enumerate(vocabulary_list):
                    term_name = term.strip()
                    if not term_name:
                        continue
                    node_id = term_node_id_by_name.get(term_name)
                    if not node_id:
                        term_data = {"name": term_name, "source": "neurosynth"}
                        term_payload = self._flatten_properties(term_data)
                        node_id = self.db.create_node("Term", term_payload)
                        if node_id:
                            term_count += 1
                            term_node_id_by_name[term_name] = node_id
                    if node_id:
                        term_node_map[term_idx] = node_id

            # Create HAS_TERM relationships from TF-IDF features
            if (
                load_features
                and features_matrix is not None
                and hasattr(features_matrix, "shape")
                and features_matrix.shape[0] > 0
                and term_node_map
                and publication_nodes_in_order
            ):
                if features_matrix.shape[0] != len(publication_nodes_in_order):
                    logger.warning(
                        "NeuroSynth feature matrix rows (%s) != processed publications (%s); skipping term relationships",
                        features_matrix.shape[0],
                        len(publication_nodes_in_order),
                    )
                else:
                    features_csr = features_matrix.tocsr()
                    term_rel_type = config.get("term_relationship_type", "HAS_TERM")
                    max_terms_per_pub = int(
                        config.get("max_terms_per_publication", 25) or 0
                    )
                    min_term_weight = float(config.get("min_term_weight", 0.0))
                    batch_threshold = max(
                        1, int(config.get("term_relationship_batch_size", 500) or 500)
                    )
                    section_tag = config.get("section", loader.section)
                    supports_bulk = hasattr(self.db, "execute_query")
                    term_rel_rows: list[dict[str, Any]] = []

                    logger.info(
                        "Linking NeuroSynth publications to terms (max %s terms per study, min weight %.4f)",
                        "unlimited" if max_terms_per_pub <= 0 else max_terms_per_pub,
                        min_term_weight,
                    )

                    def flush_term_batch() -> None:
                        nonlocal term_rel_rows, term_relationship_count
                        if not term_rel_rows:
                            return
                        if supports_bulk:
                            self.db.execute_query(
                                f"""
                                UNWIND $rows AS row
                                MATCH (p {{id: row.publication_id}})
                                MATCH (t {{id: row.term_id}})
                                MERGE (p)-[r:`{term_rel_type}`]->(t)
                                SET r += row.props
                                """,
                                {"rows": term_rel_rows},
                            )
                            term_relationship_count += len(term_rel_rows)
                        else:
                            for rel in term_rel_rows:
                                created = self.db.create_relationship(
                                    rel["publication_id"],
                                    rel["term_id"],
                                    term_rel_type,
                                    rel["props"],
                                    auto_commit=False,
                                )
                                if created:
                                    term_relationship_count += 1
                        term_rel_rows = []

                    for row_idx, pub_id in enumerate(publication_nodes_in_order):
                        if not pub_id:
                            continue
                        row = features_csr.getrow(row_idx)
                        if row.nnz == 0:
                            continue
                        indices = row.indices
                        weights = row.data
                        if min_term_weight > 0:
                            mask = weights >= min_term_weight
                            if not mask.any():
                                continue
                            indices = indices[mask]
                            weights = weights[mask]
                        if weights.size == 0:
                            continue
                        if max_terms_per_pub > 0 and weights.size > max_terms_per_pub:
                            top_idx = np.argpartition(weights, -max_terms_per_pub)[
                                -max_terms_per_pub:
                            ]
                            slice_idx = np.argsort(weights[top_idx])[::-1]
                            selected_indices = indices[top_idx][slice_idx]
                            selected_weights = weights[top_idx][slice_idx]
                        else:
                            order = np.argsort(weights)[::-1]
                            selected_indices = indices[order]
                            selected_weights = weights[order]

                        term_pairs = [
                            (int(idx), float(weight))
                            for idx, weight in zip(selected_indices, selected_weights)
                            if int(idx) in term_node_map
                        ]
                        if not term_pairs:
                            continue

                        for rank, (term_idx, weight) in enumerate(term_pairs, start=1):
                            term_node_id = term_node_map.get(term_idx)
                            if not term_node_id:
                                continue
                            term_rel_rows.append(
                                {
                                    "publication_id": pub_id,
                                    "term_id": term_node_id,
                                    "props": {
                                        "source": "neurosynth",
                                        "weight": weight,
                                        "rank": rank,
                                        "section": section_tag,
                                    },
                                }
                            )
                        if len(term_rel_rows) >= batch_threshold:
                            flush_term_batch()

                    flush_term_batch()

            stats = {
                "publications": study_count,
                "coordinates": coordinate_count,
                "relationships": relationship_count,
                "terms": term_count,
                "term_relationships": term_relationship_count,
            }

            logger.info(f"Loaded NeuroSynth: {stats}")
            self.stats["sources_loaded"].append("neurosynth")
            return stats

        except Exception as e:
            logger.exception("Failed to load NeuroSynth: %s", e)
            self.stats["errors"].append(f"neurosynth: {e}")
            return {"error": str(e)}

    def load_neurovault(
        self, config: Dict[str, Any] = None, mode: str = "full"
    ) -> Dict[str, int]:
        """
        Load NeuroVault collections with caching and optional contrast linking.

        Args:
            config: Configuration dictionary with options:
                - limit: Max collections to load (default: 10)
                - paginate_all: Load ALL collections (ignores limit)
                - load_images: Whether to load individual images (default: False)
                - mode: "full" keeps all NeuroVault fields, "spine" keeps a minimal subset
                - collection_ids: Specific collection IDs to load
                - link_contrasts: Whether to link StatMaps to Contrasts (default: True)
                - confidence_threshold: Min confidence for contrast linking (default: 0.5)
                - cache_dir: Directory for caching loaded data (default: data/neurovault/cache)

        Returns:
            Statistics about loaded data including contrast linking stats if enabled
        """
        logger.info("Loading NeuroVault data...")
        config = config or {}
        requested_mode = config.get("mode")
        mode = (requested_mode or mode or "full").lower()
        map_index_handle = None
        map_index_path = None
        map_index_count = 0

        try:
            # Use unified NeuroVault loader
            cache_dir = config.get("cache_dir", "data/neurovault/cache")
            loader = NeuroVaultUnifiedLoader(cache_dir=cache_dir)

            # Load collections or specific IDs
            collection_ids = config.get("collection_ids", [])
            limit = config.get("limit", 10)
            paginate_all = config.get("paginate_all", False)
            load_images = config.get("load_images", False)
            link_contrasts = config.get("link_contrasts", True)
            confidence_threshold = config.get("confidence_threshold", 0.5)
            write_map_index = config.get("write_map_index", False)
            paginate_images_all = config.get("paginate_images_all", False)
            collection_page_size = config.get("collection_page_size", limit)
            image_page_size = config.get(
                "image_page_size", 1000 if paginate_images_all else 100
            )
            image_fetch_mode = (
                config.get("image_fetch_mode") or "per_collection"
            ).lower()
            upsert_collections = config.get("upsert_collections", True)
            ingest_to_graph = config.get("ingest_to_graph", True)
            graph_primary_only = config.get("graph_primary_only", False)
            skip_if_no_new_images = config.get("skip_if_no_new_images", False)
            map_index_path_override = config.get("map_index_path")
            map_index_dir = Path(config.get("map_index_dir", "data/neurovault/index"))

            if collection_ids:
                collections = [loader.load_collection(cid) for cid in collection_ids]
            else:
                collections = loader.search_collections(
                    limit=collection_page_size if paginate_all else limit,
                    paginate_all=paginate_all,
                )

            # Insert into database and collect images for contrast linking
            collection_count = 0
            image_count = 0
            all_images = []  # Collect all images for contrast linking
            total_collections = sum(1 for c in collections if c)
            qa_summary = {
                "maps_kept": 0,
                "maps_skipped": 0,
                "maps_primary": 0,
                "collections_skipped": 0,
                "reasons": defaultdict(int),
                "warnings": defaultdict(int),
            }
            collection_fields = {
                "id",
                "name",
                "description",
                "owner_name",
                "doi",
                "url",
                "source",
            }
            statmap_fields = {
                "id",
                "collection_id",
                "collection",
                "url",
                "file",
                "file_size",
                "thumbnail",
                "reduced_representation",
                "surface_left_file",
                "surface_right_file",
                "map_type",
                "image_type",
                "analysis_level",
                "number_of_subjects",
                "cognitive_paradigm_cogatlas",
                "cognitive_paradigm_cogatlas_id",
                "cognitive_contrast_cogatlas",
                "cognitive_contrast_cogatlas_id",
                "target_template_image",
                "data_origin",
                "space",
                "modality",
                "is_thresholded",
                "is_valid",
                "perc_bad_voxels",
                "perc_voxels_outside",
                "brain_coverage",
                "not_mni",
                "add_date",
                "modify_date",
                "name",
                "description",
                "contrast_definition",
                "figure",
                "uri",
                "etag",
                "experiment_type",
                "source",
                "qa_status",
                "qa_reasons",
                "qa_score",
                "qa_is_primary",
            }

            if (
                write_map_index
                and skip_if_no_new_images
                and image_fetch_mode == "global"
                and not collection_ids
            ):
                current_count = loader.get_image_count()
                if map_index_path_override:
                    existing_path = Path(map_index_path_override)
                else:
                    existing_path = self._get_latest_map_index(map_index_dir)
                existing_records = 0
                if existing_path and existing_path.exists():
                    try:
                        existing_records = sum(
                            1 for _ in existing_path.open("r", encoding="utf-8")
                        )
                    except Exception:
                        existing_records = 0
                logger.info(
                    "NeuroVault image count check: api=%d, existing=%d (path=%s)",
                    current_count,
                    existing_records,
                    existing_path,
                )
                if current_count > 0 and existing_records >= current_count:
                    logger.info(
                        "Skipping NeuroVault map-index run (no new images detected)."
                    )
                    return {
                        "collections": 0,
                        "collections_total": total_collections,
                        "images": 0,
                        "map_index_path": str(existing_path) if existing_path else None,
                        "map_index_records": existing_records,
                        "qa": {
                            "maps_kept": 0,
                            "maps_skipped": 0,
                            "maps_primary": 0,
                            "collections_skipped": 0,
                            "reasons": {},
                            "warnings": {},
                        },
                    }

            if write_map_index:
                map_index_path = Path(
                    map_index_path_override
                    or (map_index_dir / f"neurovault_map_index_{self.run_id}.jsonl")
                )
                map_index_path.parent.mkdir(parents=True, exist_ok=True)
                map_index_handle = map_index_path.open("a", encoding="utf-8")
                logger.info("Writing NeuroVault map index to %s", map_index_path)

            # Phase 1: Upsert collection nodes (optional; expensive on Neo4j).
            if upsert_collections:
                for idx, collection in enumerate(collections, start=1):
                    if not collection:
                        continue

                    collection_data = dict(collection)
                    collection_data.setdefault("source", "neurovault")
                    if mode == "spine":
                        collection_data = self._filter_fields(
                            collection_data, collection_fields
                        )
                    collection_payload = self._flatten_properties(collection_data)
                    self.db.create_node("Collection", collection_payload)
                    collection_count += 1
                    if collection_count % 1000 == 0:
                        logger.info(
                            "NeuroVault collections upserted: %d/%d",
                            collection_count,
                            total_collections,
                        )
            else:
                logger.info(
                    "Skipping collection upsert (upsert_collections=False); relying on existing Collection nodes / on-demand creation.",
                )

            # Phase 2: Ingest images
            if load_images:
                collections_with_primary_maps: set[str] = set()

                if image_fetch_mode == "global" and not collection_ids:
                    logger.info(
                        "Fetching NeuroVault images via global pagination (page_size=%d)...",
                        image_page_size,
                    )
                    image_iter = loader.iter_images(
                        limit=image_page_size, paginate_all=paginate_images_all
                    )
                    for raw_image in image_iter:
                        accepted, status, warnings, score, is_primary = (
                            loader.assess_image_quality(raw_image)
                        )
                        collection_id = raw_image.get("collection_id")

                        if map_index_handle is not None:
                            record = {
                                "run_id": self.run_id,
                                "collection_id": collection_id,
                                "image_id": raw_image.get("id"),
                                "image_type": raw_image.get("image_type"),
                                "map_type": raw_image.get("map_type"),
                                "analysis_level": raw_image.get("analysis_level"),
                                "space": raw_image.get("space")
                                or raw_image.get("target_template_image"),
                                "modality": raw_image.get("modality"),
                                "is_thresholded": raw_image.get("is_thresholded"),
                                "is_valid": raw_image.get("is_valid"),
                                "perc_voxels_outside": raw_image.get(
                                    "perc_voxels_outside"
                                ),
                                "brain_coverage": raw_image.get("brain_coverage"),
                                "not_mni": raw_image.get("not_mni"),
                                "qa_accept": accepted,
                                "qa_status": status,
                                "qa_warnings": warnings,
                                "qa_score": score,
                                "qa_is_primary": is_primary,
                                "url": raw_image.get("url"),
                                "file": raw_image.get("file"),
                                "name": raw_image.get("name"),
                                "description": raw_image.get("description"),
                            }
                            map_index_handle.write(
                                json.dumps(record, ensure_ascii=False, default=str)
                                + "\n"
                            )
                            map_index_count += 1
                            if map_index_count % 1000 == 0:
                                map_index_handle.flush()
                            if map_index_count % 100000 == 0:
                                logger.info(
                                    "NeuroVault map index progress: %d images (QA-kept=%d, QA-skipped=%d)",
                                    map_index_count,
                                    qa_summary["maps_kept"],
                                    qa_summary["maps_skipped"],
                                )

                        if not accepted:
                            qa_summary["maps_skipped"] += 1
                            qa_summary["reasons"][status] += 1
                            continue

                        qa_summary["maps_kept"] += 1
                        if is_primary:
                            qa_summary["maps_primary"] += 1
                            if collection_id is not None:
                                collections_with_primary_maps.add(str(collection_id))
                        for warning in warnings:
                            qa_summary["warnings"][warning] += 1

                        if not ingest_to_graph:
                            continue
                        if graph_primary_only and not is_primary:
                            continue

                        image_data = dict(raw_image)
                        image_data.setdefault("source", "neurovault")
                        image_data["qa_status"] = status
                        image_data["qa_reasons"] = warnings
                        image_data["qa_score"] = score
                        image_data["qa_is_primary"] = is_primary

                        if link_contrasts:
                            all_images.append(dict(image_data))

                        node_props = dict(image_data)
                        if mode == "spine":
                            node_props = self._filter_fields(node_props, statmap_fields)
                        image_payload = self._flatten_properties(node_props)
                        img_node_id = self.db.create_node(
                            "StatisticalMap", image_payload
                        )
                        image_count += 1

                        if collection_id is not None:
                            collection_node_id = str(collection_id)
                            linked = self.db.create_relationship(
                                img_node_id,
                                collection_node_id,
                                "BELONGS_TO",
                                self._flatten_properties({"source": "neurovault"}),
                            )
                            if not linked:
                                self.db.create_node(
                                    "Collection",
                                    self._flatten_properties(
                                        {
                                            "id": collection_node_id,
                                            "source": "neurovault",
                                        }
                                    ),
                                )
                                self.db.create_relationship(
                                    img_node_id,
                                    collection_node_id,
                                    "BELONGS_TO",
                                    self._flatten_properties({"source": "neurovault"}),
                                )

                        if image_count % 10000 == 0:
                            logger.info(
                                "NeuroVault StatMaps ingested: %d (QA-kept=%d, QA-skipped=%d)",
                                image_count,
                                qa_summary["maps_kept"],
                                qa_summary["maps_skipped"],
                            )

                else:
                    logger.info(
                        "Fetching NeuroVault images per-collection (page_size=%d)...",
                        image_page_size,
                    )
                    collections_seen = 0
                    for collection in collections:
                        if not collection:
                            continue
                        collections_seen += 1
                        has_primary_map = False
                        raw_images = loader.search_images(
                            collection_id=collection["id"],
                            limit=image_page_size,
                            paginate_all=paginate_images_all,
                        )
                        for raw_image in raw_images:
                            accepted, status, warnings, score, is_primary = (
                                loader.assess_image_quality(raw_image)
                            )
                            if map_index_handle is not None:
                                record = {
                                    "run_id": self.run_id,
                                    "collection_id": raw_image.get("collection_id")
                                    or collection.get("id"),
                                    "image_id": raw_image.get("id"),
                                    "image_type": raw_image.get("image_type"),
                                    "map_type": raw_image.get("map_type"),
                                    "analysis_level": raw_image.get("analysis_level"),
                                    "space": raw_image.get("space")
                                    or raw_image.get("target_template_image"),
                                    "modality": raw_image.get("modality"),
                                    "is_thresholded": raw_image.get("is_thresholded"),
                                    "is_valid": raw_image.get("is_valid"),
                                    "perc_voxels_outside": raw_image.get(
                                        "perc_voxels_outside"
                                    ),
                                    "brain_coverage": raw_image.get("brain_coverage"),
                                    "not_mni": raw_image.get("not_mni"),
                                    "qa_accept": accepted,
                                    "qa_status": status,
                                    "qa_warnings": warnings,
                                    "qa_score": score,
                                    "qa_is_primary": is_primary,
                                    "url": raw_image.get("url"),
                                    "file": raw_image.get("file"),
                                    "name": raw_image.get("name"),
                                    "description": raw_image.get("description"),
                                }
                                map_index_handle.write(
                                    json.dumps(record, ensure_ascii=False, default=str)
                                    + "\n"
                                )
                                map_index_count += 1
                                if map_index_count % 1000 == 0:
                                    map_index_handle.flush()
                                if map_index_count % 100000 == 0:
                                    logger.info(
                                        "NeuroVault map index progress: %d images (QA-kept=%d, QA-skipped=%d)",
                                        map_index_count,
                                        qa_summary["maps_kept"],
                                        qa_summary["maps_skipped"],
                                    )

                            if not accepted:
                                qa_summary["maps_skipped"] += 1
                                qa_summary["reasons"][status] += 1
                                continue

                            qa_summary["maps_kept"] += 1
                            if is_primary:
                                has_primary_map = True
                                qa_summary["maps_primary"] += 1
                                collections_with_primary_maps.add(
                                    str(collection.get("id"))
                                )
                            for warning in warnings:
                                qa_summary["warnings"][warning] += 1

                            if not ingest_to_graph:
                                continue
                            if graph_primary_only and not is_primary:
                                continue

                            image_data = dict(raw_image)
                            image_data.setdefault("source", "neurovault")
                            image_data["qa_status"] = status
                            image_data["qa_reasons"] = warnings
                            image_data["qa_score"] = score
                            image_data["qa_is_primary"] = is_primary

                            if link_contrasts:
                                all_images.append(dict(image_data))

                            node_props = dict(image_data)
                            if mode == "spine":
                                node_props = self._filter_fields(
                                    node_props, statmap_fields
                                )
                            image_payload = self._flatten_properties(node_props)
                            img_node_id = self.db.create_node(
                                "StatisticalMap", image_payload
                            )
                            image_count += 1

                            collection_node_id = str(collection.get("id"))
                            linked = self.db.create_relationship(
                                img_node_id,
                                collection_node_id,
                                "BELONGS_TO",
                                self._flatten_properties({"source": "neurovault"}),
                            )
                            if not linked:
                                self.db.create_node(
                                    "Collection",
                                    self._flatten_properties(
                                        {
                                            "id": collection_node_id,
                                            "source": "neurovault",
                                        }
                                    ),
                                )
                                self.db.create_relationship(
                                    img_node_id,
                                    collection_node_id,
                                    "BELONGS_TO",
                                    self._flatten_properties({"source": "neurovault"}),
                                )

                            if image_count % 10000 == 0:
                                logger.info(
                                    "NeuroVault StatMaps ingested: %d (QA-kept=%d, QA-skipped=%d)",
                                    image_count,
                                    qa_summary["maps_kept"],
                                    qa_summary["maps_skipped"],
                                )

                        if not has_primary_map:
                            qa_summary["collections_skipped"] += 1

                        if collections_seen % 100 == 0:
                            logger.info(
                                "NeuroVault collections processed: %d/%d (collections_no_primary_maps=%d; QA-kept=%d; QA-skipped=%d; map_index=%d)",
                                collections_seen,
                                total_collections,
                                qa_summary["collections_skipped"],
                                qa_summary["maps_kept"],
                                qa_summary["maps_skipped"],
                                map_index_count,
                            )

                qa_summary["collections_skipped"] = max(
                    qa_summary["collections_skipped"],
                    max(0, total_collections - len(collections_with_primary_maps)),
                )

            stats = {
                "collections": collection_count,
                "collections_total": total_collections,
                "images": image_count,
            }
            if map_index_path is not None:
                stats["map_index_path"] = str(map_index_path)
                stats["map_index_records"] = map_index_count

            if qa_summary["maps_kept"] or qa_summary["maps_skipped"]:
                top_reasons = (
                    ", ".join(
                        f"{reason}:{count}"
                        for reason, count in sorted(
                            qa_summary["reasons"].items(),
                            key=lambda x: x[1],
                            reverse=True,
                        )[:5]
                    )
                    or "none"
                )
                top_warnings = (
                    ", ".join(
                        f"{warning}:{count}"
                        for warning, count in sorted(
                            qa_summary["warnings"].items(),
                            key=lambda x: x[1],
                            reverse=True,
                        )[:5]
                    )
                    or "none"
                )
                logger.info(
                    "NeuroVault QA summary – kept %d maps, skipped %d maps, collections_no_primary_maps=%d. Reasons: %s; warnings: %s",
                    qa_summary["maps_kept"],
                    qa_summary["maps_skipped"],
                    qa_summary["collections_skipped"],
                    top_reasons,
                    top_warnings,
                )
                unsupported_counts = loader.get_unsupported_map_type_counts()
                if unsupported_counts:
                    top_unsupported = ", ".join(
                        f"{map_type}:{count}"
                        for map_type, count in sorted(
                            unsupported_counts.items(), key=lambda x: x[1], reverse=True
                        )[:20]
                    )
                    logger.info(
                        "UNSUPPORTED_MAP_TYPE top 20 (counted during QA): %s",
                        top_unsupported or "none",
                    )
                    histogram_path = (
                        Path("logs")
                        / f"neurovault_unsupported_map_types_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    )
                    histogram_path.parent.mkdir(parents=True, exist_ok=True)
                    with histogram_path.open("w") as f:
                        json.dump(
                            dict(
                                sorted(
                                    unsupported_counts.items(),
                                    key=lambda x: (-x[1], x[0]),
                                )
                            ),
                            f,
                            indent=2,
                        )
                    logger.info(
                        "UNSUPPORTED_MAP_TYPE histogram written to %s",
                        histogram_path,
                    )
                out_of_bounds_hist = loader.get_out_of_bounds_histogram()
                if out_of_bounds_hist:
                    top_oob = ", ".join(
                        f"{bucket}:{count}"
                        for bucket, count in sorted(
                            out_of_bounds_hist.items(), key=lambda x: x[1], reverse=True
                        )[:20]
                    )
                    logger.info(
                        "OUT_OF_BOUNDS histogram top 20 (perc_voxels_outside): %s",
                        top_oob or "none",
                    )
                    oob_path = (
                        Path("logs")
                        / f"neurovault_out_of_bounds_hist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    )
                    oob_path.parent.mkdir(parents=True, exist_ok=True)
                    with oob_path.open("w") as f:
                        json.dump(
                            dict(
                                sorted(
                                    out_of_bounds_hist.items(),
                                    key=lambda x: (-x[1], x[0]),
                                )
                            ),
                            f,
                            indent=2,
                        )
                    logger.info("OUT_OF_BOUNDS histogram written to %s", oob_path)

            stats["qa"] = {
                "maps_kept": qa_summary["maps_kept"],
                "maps_skipped": qa_summary["maps_skipped"],
                "maps_primary": qa_summary["maps_primary"],
                "collections_skipped": qa_summary["collections_skipped"],
                "reasons": dict(qa_summary["reasons"]),
                "warnings": dict(qa_summary["warnings"]),
            }

            # Phase 2: Link contrasts using enhanced loader
            if link_contrasts and all_images and load_images:
                total_maps = len(all_images)
                logger.info(f"Starting contrast linking for {total_maps} images...")

                # Cache images to JSON for resilience
                cache_path = (
                    Path(cache_dir)
                    / f"neurovault_images_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                )
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("w") as f:
                    json.dump({"statistical_maps": all_images}, f, indent=2)
                logger.info(f"Cached {total_maps} images to {cache_path}")

                # Run enhanced loader for contrast linking
                enhanced_loader = EnhancedNeuroVaultLoader(self.db)
                linking_stats = enhanced_loader.ingest_from_file(cache_path)

                # Merge stats
                stats.update(
                    {"contrast_linking": linking_stats, "cache_file": str(cache_path)}
                )
                logger.info(
                    "Contrast linking complete: %d/%d matched",
                    linking_stats.get("contrasts_matched", 0),
                    linking_stats.get("maps_processed", total_maps),
                )
            elif link_contrasts and not load_images:
                logger.warning(
                    "link_contrasts=True but load_images=False. Skipping contrast linking."
                )

            logger.info(f"Loaded NeuroVault: {stats}")
            self.stats["sources_loaded"].append("neurovault")
            return stats

        except Exception as e:
            logger.error(f"Failed to load NeuroVault: {e}")
            self.stats["errors"].append(f"neurovault: {e}")
            return {"error": str(e)}
        finally:
            try:
                if map_index_handle is not None:
                    map_index_handle.close()
            except Exception:
                pass

    def load_openneuro(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load OpenNeuro datasets with GraphQL API.

        Args:
            config: Configuration dictionary

        Returns:
            Statistics about loaded data
        """
        logger.info("Loading OpenNeuro data...")
        config = config or {}
        mode = (mode or "spine").lower()

        try:
            # Use unified OpenNeuro loader
            loader = OpenNeuroUnifiedLoader(
                cache_dir=config.get("cache_dir", "data/openneuro/cache"),
                data_dir=config.get("download_dir", "data/bids"),
            )

            # Load datasets
            dataset_ids = config.get("datasets", [])
            limit = config.get("limit", 10)
            download_data = config.get("download_data", False)

            if dataset_ids:
                datasets = [loader.get_dataset_details(did) for did in dataset_ids]
            else:
                datasets = loader.query_datasets(limit=limit)

            # Insert into database
            dataset_count = 0
            task_count = 0

            dataset_fields = {
                "id",
                "name",
                "description",
                "license",
                "modalities",
                "tasks",
                "subjects_count",
                "tr",
                "te",
                "url",
                "source",
            }
            task_fields = {"id", "name", "synonyms", "source"}

            for dataset in datasets:
                if dataset:
                    dataset_data = dict(dataset)
                    dataset_data.setdefault("source", "openneuro")
                    if mode == "spine":
                        dataset_data = self._filter_fields(dataset_data, dataset_fields)
                    dataset_payload = self._flatten_properties(dataset_data)
                    node_id = self.db.create_node("Dataset", dataset_payload)
                    if node_id:
                        dataset_count += 1

                        # Extract and link tasks
                        if mode == "full" and "tasks" in dataset:
                            for task in dataset.get("tasks", []) or []:
                                task_data = dict(task)
                                task_data.setdefault("source", "openneuro")
                                task_payload = self._flatten_properties(task_data)
                                task_node_id = self.db.create_node("Task", task_payload)
                                if task_node_id:
                                    task_count += 1
                                    self.db.create_relationship(
                                        node_id,
                                        task_node_id,
                                        "CONTAINS_TASK",
                                        self._flatten_properties(
                                            {"source": "openneuro"}
                                        ),
                                    )

                        # Download data if requested
                        if download_data:
                            loader.download_dataset(
                                dataset["id"],
                                download_bids=True,
                                download_derivatives=config.get(
                                    "download_derivatives", False
                                ),
                            )

            stats = {"datasets": dataset_count, "tasks": task_count}

            if config.get("apply_onvoc_annotations"):
                annotation_loader = OpenNeuroOnvocAnnotationLoader(
                    annotations_path=config.get("onvoc_annotations_path"),
                    onvoc_dir=config.get("onvoc_dir", "data/ontologies/onvoc"),
                )
                annotation_stats = OpenNeuroOnvocAnnotationApplier(
                    self.db,
                    loader=annotation_loader,
                ).apply()
                stats.update(
                    {
                        "annotation_records": annotation_stats["records_processed"],
                        "annotation_datasets_created": annotation_stats[
                            "datasets_created"
                        ],
                        "annotation_positive_links": annotation_stats[
                            "positive_links_created"
                        ],
                        "annotation_exclusion_links": annotation_stats[
                            "exclusion_links_created"
                        ],
                        "annotation_missing_reference_terms": len(
                            annotation_stats["missing_reference_terms"]
                        ),
                        "annotation_missing_graph_terms": len(
                            annotation_stats["missing_graph_terms"]
                        ),
                        "annotation_label_mismatches": len(
                            annotation_stats["label_mismatches"]
                        ),
                    }
                )
                study_stats = link_openneuro_dataset_studies(self.db)
                stats.update(
                    {
                        "dataset_study_links_created": study_stats[
                            "study_links_created"
                        ],
                        "datasets_with_study_links": study_stats[
                            "datasets_with_study_links"
                        ],
                    }
                )
                alignment_stats = link_publication_study_alignments(self.db)
                stats.update(
                    {
                        "publication_study_alignments_created": alignment_stats[
                            "alignment_edges_created"
                        ],
                        "publication_study_alignments_existing": alignment_stats[
                            "alignment_edges_existing"
                        ],
                    }
                )

            logger.info(f"Loaded OpenNeuro: {stats}")
            self.stats["sources_loaded"].append("openneuro")
            return stats

        except Exception as e:
            logger.error(f"Failed to load OpenNeuro: {e}")
            self.stats["errors"].append(f"openneuro: {e}")
            return {"error": str(e)}

    def load_openneuro_glmfitlins(
        self,
        config: Dict[str, Any] | None = None,
        mode: str = "full",
    ) -> Dict[str, Any]:
        """Ingest OpenNeuro GLM FitLins statistical maps."""

        config = config or {}
        path_config_path = Path(
            config.get(
                "path_config",
                "data/openneuro_glmfitlins/path_config.local.json",
            )
        )
        manifest_path = config.get("manifest_path")
        statsmodel_dir = config.get(
            "statsmodel_dir",
            "data/openneuro_glmfitlins/statsmodel_specs",
        )
        compute_checksum = bool(config.get("compute_checksum", False))

        logger.info(
            "Starting OpenNeuro GLM FitLins ingest (statsmodel_dir=%s, manifest=%s, mode=%s)",
            statsmodel_dir,
            manifest_path,
            mode,
        )

        limit = config.get("limit")
        if limit is None and mode.lower() != "full":
            # Provide a conservative default when running in sample/quick mode
            limit = 200

        try:
            path_config = load_glmfitlins_path_config(path_config_path)
            loader = OpenNeuroGLMFitlinsLoader.from_config(
                path_config,
                manifest_path=manifest_path,
                compute_checksum=compute_checksum,
                onvoc_linker_factory=OnvocLinker,
                construct_manager_factory=ConstructManager,
            )

            stats = loader.ingest(
                self.db,
                statsmodel_dir=Path(statsmodel_dir) if statsmodel_dir else None,
                limit=limit,
            )

            logger.info("Loaded OpenNeuro GLM FitLins maps: %s", stats)
            self.stats["sources_loaded"].append("openneuro_glmfitlins")
            return stats

        except Exception as exc:
            logger.error("Failed to load OpenNeuro GLM FitLins: %s", exc)
            self.stats["errors"].append(f"openneuro_glmfitlins: {exc}")
            return {"error": str(exc)}

    def load_wikidata(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load WikiData brain regions via SPARQL.

        Args:
            config: Configuration dictionary

        Returns:
            Statistics about loaded data
        """
        logger.info("Loading WikiData brain regions...")
        config = config or {}
        mode = (mode or "spine").lower()

        try:
            # Use unified WikiData loader
            loader = WikiDataUnifiedLoader(
                cache_dir=config.get("cache_dir", "data/wikidata/cache")
            )

            # Load brain regions
            limit = config.get("limit", 500)
            regions = loader.load_brain_regions(limit=limit)

            # Insert into database
            region_count = 0
            hierarchy_count = 0

            spine_fields = {"id", "name", "aliases", "atlas", "source"}

            for region in regions:
                region_data = dict(region)
                region_data.setdefault("source", "wikidata")
                if mode == "spine":
                    region_data = self._filter_fields(region_data, spine_fields)
                region_payload = self._flatten_properties(region_data)
                node_id = self.db.create_node("BrainRegion", region_payload)
                if node_id:
                    region_count += 1

                    # Create hierarchical relationships if present
                    if "parent_id" in region:
                        rel_id = self.db.create_relationship(
                            node_id,
                            region["parent_id"],
                            "PART_OF",
                            self._flatten_properties({"source": "wikidata"}),
                        )
                        if rel_id:
                            hierarchy_count += 1

            stats = {"brain_regions": region_count, "hierarchies": hierarchy_count}

            logger.info(f"Loaded WikiData: {stats}")
            self.stats["sources_loaded"].append("wikidata")
            return stats

        except Exception as e:
            logger.error(f"Failed to load WikiData: {e}")
            self.stats["errors"].append(f"wikidata: {e}")
            return {"error": str(e)}

    def load_neuromaps(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """
        Load Neuromaps parcellations into the BR-KG database.

        Args:
            config: Configuration dictionary.

        Returns:
            Dictionary with ingestion statistics.
        """
        logger.info("Loading Neuromaps parcellations...")
        config = config or {}
        mode = (mode or "spine").lower()

        base_path = config.get("base_path", str(preferred_neuromaps_root()))
        dry_run = bool(config.get("dry_run", False))
        include_restricted = config.get("include_restricted")

        loader = NeuromapsUnifiedLoader(base_path=base_path)
        include = (
            config.get("include_atlases")
            or config.get("include")
            or config.get("atlas")
        )
        exclude = config.get("exclude_atlases") or config.get("exclude")

        try:
            result = loader.load(
                db=self.db,
                include=include,
                exclude=exclude,
                dry_run=dry_run,
                include_restricted=include_restricted,
            )
        except FileNotFoundError as exc:
            logger.error("Neuromaps base path not found: %s", exc)
            self.stats["errors"].append(f"neuromaps: {exc}")
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive catch
            logger.error(
                "Failed to ingest Neuromaps parcellations: %s", exc, exc_info=True
            )
            self.stats["errors"].append(f"neuromaps: {exc}")
            return {"error": str(exc)}

        annotations_created = result.get("annotations_created", 0)
        annotations_updated = result.get("annotations_updated", 0)
        if (
            result["atlases_processed"] == 0
            and result["atlases_failed"] > 0
            and annotations_created == 0
            and annotations_updated == 0
        ):
            self.stats["errors"].append(
                "neuromaps: all discovered atlases failed to ingest; inspect log output."
            )
        elif annotations_created or annotations_updated:
            logger.info(
                "Recorded Neuromaps annotation metadata nodes (created=%d, updated=%d, discovered=%d, skipped=%d)",
                annotations_created,
                annotations_updated,
                result.get("annotations_discovered", 0),
                result.get("annotations_skipped", 0),
            )

        self.stats["sources_loaded"].append("neuromaps")
        return result

    def load_niclip_embeddings(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """Ingest NICLIP text and activation embeddings into the graph."""

        logger.info("Loading NICLIP embeddings...")
        config = config or {}
        mode = (mode or "spine").lower()

        try:
            logger.info("NICLIP config: %s", config)
            loader = NICLIPEmbeddingLoader(
                root_path=config.get(
                    "niclip_path",
                    os.environ.get("NICLIP_DATA_PATH", "/app/data/niclip"),
                )
            )
            logger.info(
                "NICLIP loader initialized (root=%s)", getattr(loader, "root", None)
            )

            batch_size = int(config.get("niclip_embedding_batch_size", 5000) or 5000)
            store_vectors = bool(config.get("store_vectors", False))
            load_text = config.get("load_text_embeddings", True)
            load_activation = config.get("load_coordinate_embeddings", True)
            logger.info(
                "NICLIP ingest params: batch_size=%s store_vectors=%s load_text=%s load_activation=%s",
                batch_size,
                store_vectors,
                load_text,
                load_activation,
            )

            text_batch = None
            if load_text:
                logger.info("Loading NICLIP text embeddings...")
                text_batch = loader.get_text_embeddings(
                    model=config.get("text_model", "BrainGPT-7B-v0.2"),
                    section=config.get(
                        "text_section", config.get("niclip_text_section", "abstract")
                    ),
                    normalization=config.get(
                        "text_normalization",
                        config.get("niclip_text_normalization", "normalized"),
                    ),
                )
                if text_batch is None:
                    logger.warning("No NICLIP text embeddings returned")
                else:
                    logger.info(
                        "Loaded NICLIP text batch: %s (model=%s section=%s)",
                        text_batch.embeddings.shape,
                        text_batch.metadata.get("model"),
                        text_batch.metadata.get("section"),
                    )

            coord_batch = None
            if load_activation:
                logger.info("Loading NICLIP coordinate embeddings...")
                coord_batch = loader.get_coordinate_embeddings(
                    method=config.get("coord_method", "MKDA"),
                    normalization=config.get("coord_normalization", "standardized"),
                    model=config.get("coord_model", "BrainGPT-7B-v0.2"),
                    summary=config.get("coord_summary"),
                    file_override=config.get("coord_embedding_path"),
                )
                if coord_batch is None:
                    logger.warning("No NICLIP coordinate embeddings returned")
                else:
                    logger.info(
                        "Loaded NICLIP coord batch: %s (model=%s method=%s summary=%s)",
                        coord_batch.embeddings.shape,
                        coord_batch.metadata.get("model"),
                        coord_batch.metadata.get("method"),
                        coord_batch.metadata.get("summary"),
                    )

            if text_batch is None and coord_batch is None:
                logger.info("No NICLIP batches were requested or available")
                return {"embeddings": 0, "models": 0}

            max_embeddings = config.get("niclip_max_embeddings")
            start_offset = int(config.get("niclip_start_offset", 0) or 0)
            if start_offset:
                if (
                    text_batch is not None
                    and text_batch.embeddings.shape[0] > start_offset
                ):
                    text_batch = EmbeddingBatch(
                        embeddings=text_batch.embeddings[start_offset:],
                        study_ids=text_batch.study_ids[start_offset:],
                        file_path=text_batch.file_path,
                        metadata=text_batch.metadata,
                    )
                    logger.info("Skipped first %d NICLIP text rows", start_offset)
                if (
                    coord_batch is not None
                    and coord_batch.embeddings.shape[0] > start_offset
                ):
                    coord_batch = EmbeddingBatch(
                        embeddings=coord_batch.embeddings[start_offset:],
                        study_ids=coord_batch.study_ids[start_offset:],
                        file_path=coord_batch.file_path,
                        metadata=coord_batch.metadata,
                    )
                    logger.info("Skipped first %d NICLIP coord rows", start_offset)

            if max_embeddings:
                limit = max(1, int(max_embeddings))
                if text_batch is not None and text_batch.embeddings.shape[0] > limit:
                    text_batch = EmbeddingBatch(
                        embeddings=text_batch.embeddings[:limit],
                        study_ids=text_batch.study_ids[:limit],
                        file_path=text_batch.file_path,
                        metadata=text_batch.metadata,
                    )
                    logger.info("Truncated NICLIP text batch to %d rows", limit)
                if coord_batch is not None and coord_batch.embeddings.shape[0] > limit:
                    coord_batch = EmbeddingBatch(
                        embeddings=coord_batch.embeddings[:limit],
                        study_ids=coord_batch.study_ids[:limit],
                        file_path=coord_batch.file_path,
                        metadata=coord_batch.metadata,
                    )
                    logger.info("Truncated NICLIP coord batch to %d rows", limit)

            def _lookup_publications(study_ids: List[str]) -> dict[str, str]:
                keys = sorted({sid for sid in study_ids if sid})
                if not keys:
                    return {}
                mapping: dict[str, str] = {}
                ns_ids = [f"neurosynth:{sid}" for sid in keys]
                if hasattr(self.db, "execute_query"):
                    result = self.db.execute_query(
                        (
                            "MATCH (p:Publication) "
                            "WHERE p.pmid IN $pmids OR p.neurosynth_id IN $ns OR p.id IN $ns "
                            "RETURN p"
                        ),
                        {"pmids": keys, "ns": ns_ids},
                    )
                    for row in result:
                        node = row.get("p")
                        if not node:
                            continue
                        node_id = node.get("id") or getattr(node, "element_id", None)
                        if not node_id:
                            continue
                        props = dict(node)

                        def _record(key: Any) -> None:
                            if not key:
                                return
                            key_str = str(key)
                            mapping[key_str] = node_id
                            if key_str.startswith("neurosynth:"):
                                mapping[key_str.split("neurosynth:", 1)[1]] = node_id

                        _record(props.get("pmid"))
                        _record(props.get("id"))
                        _record(props.get("neurosynth_id"))
                remaining = [sid for sid in keys if sid not in mapping]
                if remaining:
                    mapping.update(
                        self.db.bulk_find_nodes_by_pmid(remaining, label="Publication")
                    )
                return mapping

            def _prepare_embedding_meta(
                kind: str,
                batch: EmbeddingBatch,
                idx: int,
                store_vector: bool,
            ) -> dict[str, Any]:
                vector = batch.embeddings[idx]
                if vector.ndim > 1:
                    vector = vector.ravel()
                study_id = batch.study_ids[idx]
                metadata = {
                    "id": (
                        f"embedding:niclip:{kind}:{batch.metadata.get('model', 'unknown')}:{study_id}:{idx}"
                    ),
                    "kind": kind,
                    "model": batch.metadata.get("model"),
                    "normalization": batch.metadata.get("normalization"),
                    "dimension": int(vector.shape[0]),
                    "owner_id": study_id,
                    "source": "niclip",
                    "storage_path": batch.file_path,
                    "storage_index": idx,
                    "vector_norm": float(np.linalg.norm(vector)),
                }
                if kind == "text" and batch.metadata.get("section"):
                    metadata["text_section"] = batch.metadata["section"]
                if kind == "activation":
                    if batch.metadata.get("method"):
                        metadata["activation_method"] = batch.metadata["method"]
                    if batch.metadata.get("summary"):
                        metadata["activation_summary"] = batch.metadata["summary"]
                if store_vector:
                    metadata["vector"] = vector.astype(np.float32).tolist()
                return metadata

            def _filter_embedding_props(props: dict[str, Any]) -> dict[str, Any]:
                if mode != "spine":
                    return props
                allowed = {
                    "id",
                    "kind",
                    "model",
                    "text_section",
                    "activation_method",
                    "activation_summary",
                    "normalization",
                    "dimension",
                    "owner_id",
                    "source",
                    "storage_path",
                    "storage_index",
                    "vector_norm",
                }
                if "vector" in props:
                    allowed.add("vector")
                return {
                    k: v for k, v in props.items() if k in allowed and v is not None
                }

            def _filter_relationship_props(props: dict[str, Any]) -> dict[str, Any]:
                if mode != "spine":
                    return props
                allowed = {
                    "kind",
                    "model",
                    "text_section",
                    "activation_method",
                    "activation_summary",
                }
                return {
                    k: v for k, v in props.items() if k in allowed and v is not None
                }

            def _ingest_batch(
                batch: EmbeddingBatch,
                kind: str,
                rel_type: str,
                rel_base: Dict[str, Any],
            ) -> Tuple[int, int]:
                if batch is None:
                    return 0, 0
                publication_lookup = _lookup_publications(batch.study_ids)
                total = len(batch.study_ids)
                created_nodes = 0
                created_rels = 0
                for start in range(0, total, batch_size):
                    end = min(start + batch_size, total)
                    node_payloads: List[Tuple[str, dict[str, Any]]] = []
                    for idx in range(start, end):
                        meta = _prepare_embedding_meta(kind, batch, idx, store_vectors)
                        node_payloads.append(
                            ("Embedding", _filter_embedding_props(meta))
                        )
                    node_ids = self.db.bulk_create_nodes(
                        node_payloads, batch_size=batch_size
                    )
                    created_nodes += len(node_ids)
                    for node_id, idx in zip(node_ids, range(start, end)):
                        study_id = batch.study_ids[idx]
                        pub_id = publication_lookup.get(
                            study_id
                        ) or publication_lookup.get(f"neurosynth:{study_id}")
                        if not pub_id:
                            continue
                        rel_props = dict(rel_base)
                        rel_props.setdefault("kind", kind)
                        rel_props = _filter_relationship_props(rel_props)
                        created = self.db.create_relationship(
                            pub_id,
                            node_id,
                            rel_type,
                            rel_props,
                            auto_commit=False,
                        )
                        if created:
                            created_rels += 1
                    self.db.commit()
                    logger.info(
                        "Committed NICLIP %s embeddings batch %s/%s",
                        kind,
                        end,
                        total,
                    )
                return created_nodes, created_rels

            embedding_count = 0
            text_rel_count = 0
            if text_batch is not None:
                text_nodes, text_rels = _ingest_batch(
                    text_batch,
                    "text",
                    "HAS_TEXT_EMBEDDING",
                    {
                        "model": text_batch.metadata.get("model"),
                        "text_section": text_batch.metadata.get("section"),
                        "normalization": text_batch.metadata.get("normalization"),
                    },
                )
                embedding_count += text_nodes
                text_rel_count += text_rels
                logger.info("Created %d HAS_TEXT_EMBEDDING relationships", text_rels)

            coord_rel_count = 0
            if coord_batch is not None:
                coord_nodes, coord_rels = _ingest_batch(
                    coord_batch,
                    "activation",
                    "HAS_ACTIVATION_EMBEDDING",
                    {
                        "model": coord_batch.metadata.get("model"),
                        "activation_method": coord_batch.metadata.get("method"),
                        "activation_summary": coord_batch.metadata.get("summary"),
                        "normalization": coord_batch.metadata.get("normalization"),
                    },
                )
                embedding_count += coord_nodes
                coord_rel_count += coord_rels
                logger.info(
                    "Created %d HAS_ACTIVATION_EMBEDDING relationships", coord_rels
                )

            models = loader.get_trained_models()
            model_count = 0
            if mode == "full":
                for model_type, model_info in models.items():
                    model_payload = self._flatten_properties(
                        {"type": model_type, "info": model_info}
                    )
                    node_id = self.db.create_node("Model", model_payload)
                    if node_id:
                        model_count += 1

            stats = {"embeddings": embedding_count, "models": model_count}

            logger.info(
                "Loaded NICLIP embeddings (text_rels=%s, activation_rels=%s)",
                text_rel_count,
                coord_rel_count,
            )
            self.stats["sources_loaded"].append("niclip")
            return stats

        except Exception as e:
            logger.exception("Failed to load NICLIP (config=%s)", config)
            self.stats["errors"].append(f"niclip: {e}")
            return {"error": str(e)}

    def load_brainmap(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load BrainMap experiment database.

        Args:
            config: Configuration dictionary

        Returns:
            Statistics about loaded data
        """
        logger.info("Loading BrainMap data...")
        config = config or {}
        mode = (mode or "spine").lower()

        try:
            # Use BrainMap unified loader
            loader = BrainMapUnifiedLoader(
                workspace_path=config.get(
                    "workspace_path",
                    os.environ.get("BRAINMAP_WORKSPACE_PATH", "/app/data/brainmap"),
                ),
                use_api=config.get("use_api", False),
                cache_dir=config.get("cache_dir", "/tmp/brainmap_cache"),
            )

            # Parse experiments
            experiments = loader.parse_experiments()

            # Extract components
            contrasts = loader.extract_contrasts(experiments)
            domain_mappings = loader.map_domains_to_cognitive_atlas()
            coord_data = loader.import_coordinates_with_metadata()
            paper_links = loader.link_papers_to_pubmed()

            # Insert into database
            experiment_count = 0
            contrast_count = 0
            coordinate_count = 0
            paper_count = 0

            experiment_fields = {"id", "name", "pmid", "task_id", "source"}
            contrast_fields = {"id", "task_id", "label", "source"}
            coordinate_fields = {"id", "space", "round_mm", "x", "y", "z", "source"}
            publication_fields = {"pmid", "doi", "title", "year", "journal", "source"}

            # Insert experiments
            for exp in experiments:
                exp_data = dict(exp)
                exp_data.setdefault("source", "brainmap")
                if mode == "spine":
                    exp_data = self._filter_fields(exp_data, experiment_fields)
                experiment_payload = self._flatten_properties(exp_data)
                node_id = self.db.create_node("Experiment", experiment_payload)
                if node_id:
                    experiment_count += 1

            # Insert contrasts
            for contrast in contrasts:
                contrast_data = dict(contrast)
                contrast_data.setdefault("source", "brainmap")
                if mode == "spine":
                    contrast_data = self._filter_fields(contrast_data, contrast_fields)
                contrast_payload = self._flatten_properties(contrast_data)
                node_id = self.db.create_node("Contrast", contrast_payload)
                if node_id:
                    contrast_count += 1

            # Insert coordinates with clusters
            for coord in coord_data.get("coordinates", []):
                coord = dict(coord)
                origin_hint = coord.get("experiment_id") or coord.get("study_id")
                try:
                    coord_id = self._generate_coordinate_id(
                        coord, origin_hint=origin_hint
                    )
                except ValueError:
                    logger.debug(
                        "Skipping BrainMap coordinate with invalid axes: %s", coord
                    )
                    continue
                coord_props = {
                    "id": coord_id,
                    "space": coord.get("space"),
                    "x": coord.get("x"),
                    "y": coord.get("y"),
                    "z": coord.get("z"),
                    "round_mm": coord.get("rounding_mm") or self.coordinate_rounding_mm,
                    "source": "brainmap",
                }
                if mode == "spine":
                    coord_props = self._filter_fields(coord_props, coordinate_fields)
                coord_payload = self._flatten_properties(coord_props)
                node_id = self.db.create_node("Coordinate", coord_payload)
                if node_id:
                    coordinate_count += 1

            # Insert linked papers
            for paper in paper_links.get("linked_papers", []):
                paper_data = dict(paper)
                paper_data.setdefault("source", "brainmap")
                if mode == "spine":
                    paper_data = self._filter_fields(paper_data, publication_fields)
                paper_payload = self._flatten_properties(paper_data)
                node_id = self.db.create_node("Publication", paper_payload)
                if node_id:
                    paper_count += 1

            # Create domain-concept relationships
            for domain, mapping in domain_mappings.items():
                if mapping.get("best_match"):
                    # Create relationship between domain and CA concept
                    rel_props = {"confidence": mapping["best_match"]["confidence"]}
                    self.db.create_relationship(
                        domain,
                        mapping["best_match"]["concept_id"],
                        "MAPS_TO",
                        self._flatten_properties(rel_props),
                    )

            stats = {
                "experiments": experiment_count,
                "contrasts": contrast_count,
                "coordinates": coordinate_count,
                "papers": paper_count,
                "clusters": coord_data.get("n_clusters", 0),
            }

            logger.info(f"Loaded BrainMap: {stats}")
            self.stats["sources_loaded"].append("brainmap")
            return stats

        except Exception as e:
            logger.error(f"Failed to load BrainMap: {e}")
            self.stats["errors"].append(f"brainmap: {e}")
            return {"error": str(e)}

    def load_neurostore(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load Neurostore study metadata and task annotations.
        """
        logger.info("Loading Neurostore data...")
        config = config or {}
        mode = (mode or "spine").lower()

        include_fmri = config.get("include_fmri", True)
        include_behavioral = config.get("include_behavioral", True)
        relationship_type = config.get("relationship_type", "REPORTS_TASK")
        use_embedding_linker = config.get("use_embedding_linker", True)

        try:
            task_resolver = TaskTaxonomyResolver(self.db)
            loader = NeurostoreUnifiedLoader(
                data_dir=config.get("data_dir"),
                include_invalid=config.get("include_invalid", False),
                alias_map_path=config.get("alias_map_path"),
                alias_map=config.get("alias_map"),
                task_resolver=task_resolver,
            )

            loader.load_studies()
            loader.extract_tasks(
                include_fmri=include_fmri,
                include_behavioral=include_behavioral,
            )

            collections = loader.prepare_collections()
            publications = loader.prepare_publications()
            task_nodes = loader.prepare_task_nodes(
                include_fmri=include_fmri,
                include_behavioral=include_behavioral,
            )
            collection_relationships = loader.prepare_relationships(
                relationship_type=relationship_type,
                start_field="collection_id",
            )
            publication_relationships = loader.prepare_relationships(
                relationship_type=relationship_type,
                start_field="publication_id",
            )

            publication_count = 0
            collection_count = 0
            task_count = 0
            relationship_count = 0
            dois_for_metadata: Set[str] = set()

            publication_node_map: Dict[str, str] = {}
            collection_node_map: Dict[str, str] = {}
            existing_publications_by_pmid: Dict[str, tuple[str, dict[str, Any]]] = {}
            existing_publications_by_id: Dict[str, tuple[str, dict[str, Any]]] = {}
            existing_collections_by_id: Dict[str, tuple[str, dict[str, Any]]] = {}
            existing_tasks_by_id: Dict[str, tuple[str, dict[str, Any]]] = {}

            for node_id, node_props in self.db.find_nodes("Publication"):
                node_data = dict(node_props)
                labels = node_data.get("labels") or ["Publication"]
                node_data.setdefault("labels", labels)
                node_identifier = node_data.get("id") or node_id
                if node_identifier:
                    existing_publications_by_id[str(node_identifier)] = (
                        node_id,
                        node_data,
                    )
                node_pmid = node_data.get("pmid")
                if node_pmid:
                    existing_publications_by_pmid[str(node_pmid)] = (node_id, node_data)
            for node_id, node_props in self.db.find_nodes("Collection"):
                node_data = dict(node_props)
                labels = node_data.get("labels") or ["Collection"]
                node_data.setdefault("labels", labels)
                node_identifier = node_data.get("id") or node_id
                if node_identifier:
                    existing_collections_by_id[str(node_identifier)] = (
                        node_id,
                        node_data,
                    )
            for node_id, node_props in self.db.find_nodes("Task"):
                node_data = dict(node_props)
                labels = node_data.get("labels") or ["Task"]
                node_data.setdefault("labels", labels)
                node_identifier = node_data.get("id") or node_id
                if node_identifier:
                    existing_tasks_by_id[str(node_identifier)] = (node_id, node_data)

            publication_fields = {
                "id",
                "pmid",
                "doi",
                "title",
                "year",
                "journal",
                "source",
            }
            collection_fields = None
            task_fields = (
                None if mode == "full" else {"id", "name", "synonyms", "source"}
            )
            if mode != "full":
                collection_fields = {
                    "id",
                    "name",
                    "title",
                    "study_id",
                    "publication_id",
                    "modalities",
                    "study_objective",
                    "source",
                }

            for publication in publications:
                node_id: Optional[str] = None
                node_data: Optional[dict[str, Any]] = None

                pmid = publication.get("pmid")
                if pmid and str(pmid) in existing_publications_by_pmid:
                    node_id, node_data = existing_publications_by_pmid[str(pmid)]
                elif publication["id"] in existing_publications_by_id:
                    node_id, node_data = existing_publications_by_id[publication["id"]]

                if node_id and node_data:
                    updated = False
                    for key, value in publication.items():
                        sanitized_value = self._flatten_value(value)
                        if key not in node_data or (
                            not node_data.get(key) and sanitized_value
                        ):
                            node_data[key] = sanitized_value
                            updated = True
                    if updated:
                        sanitized_node = dict(node_data)
                        if mode == "spine":
                            sanitized_node = self._filter_fields(
                                sanitized_node, publication_fields
                            )
                        sanitized_node = self._flatten_properties(sanitized_node)
                        for prop_key, prop_value in sanitized_node.items():
                            node_data[prop_key] = prop_value
                        self.db._save_node(
                            node_id,
                            sanitized_node.get("labels", ["Publication"]),
                            sanitized_node,
                        )
                else:
                    publication_payload = dict(publication)
                    if mode == "spine":
                        publication_payload = self._filter_fields(
                            publication_payload, publication_fields
                        )
                    publication_payload = self._flatten_properties(publication_payload)
                    node_id = self.db.create_node("Publication", publication_payload)
                    if node_id:
                        publication_count += 1
                        node_data = self.db.get_node(node_id)

                if node_id and node_data:
                    if pmid:
                        existing_publications_by_pmid[str(pmid)] = (node_id, node_data)
                    existing_publications_by_id[publication["id"]] = (
                        node_id,
                        node_data,
                    )
                    publication_node_map[publication["id"]] = node_id
                    dois_for_metadata |= self._collect_dois(publication)

            for collection in collections:
                node_id: Optional[str] = None
                node_data: Optional[dict[str, Any]] = None
                collection_id_value = collection["id"]
                if collection_id_value in existing_collections_by_id:
                    node_id, node_data = existing_collections_by_id[collection_id_value]

                if node_id and node_data:
                    updated = False
                    for key, value in collection.items():
                        sanitized_value = self._flatten_value(value)
                        if key not in node_data or (
                            not node_data.get(key) and sanitized_value
                        ):
                            node_data[key] = sanitized_value
                            updated = True
                    if updated:
                        sanitized_node = dict(node_data)
                        if mode == "spine" and collection_fields:
                            sanitized_node = self._filter_fields(
                                sanitized_node, collection_fields
                            )
                        sanitized_node = self._flatten_properties(sanitized_node)
                        for prop_key, prop_value in sanitized_node.items():
                            node_data[prop_key] = prop_value
                        self.db._save_node(
                            node_id,
                            sanitized_node.get("labels", ["Collection"]),
                            sanitized_node,
                        )
                else:
                    collection_payload = dict(collection)
                    if mode == "spine" and collection_fields:
                        collection_payload = self._filter_fields(
                            collection_payload, collection_fields
                        )
                    collection_payload = self._flatten_properties(collection_payload)
                    node_id = self.db.create_node("Collection", collection_payload)
                    if node_id:
                        collection_count += 1
                        node_data = self.db.get_node(node_id)

                if node_id and node_data:
                    existing_collections_by_id[collection_id_value] = (
                        node_id,
                        node_data,
                    )
                    collection_node_map[collection_id_value] = node_id

            task_node_map: Dict[str, str] = {}
            for task in task_nodes:
                task_payload = dict(task)
                task_payload.setdefault("source", "neurostore")
                if task_fields:
                    task_payload = self._filter_fields(task_payload, task_fields)
                task_payload = self._flatten_properties(task_payload)

                node_id: Optional[str] = None
                node_data: Optional[dict[str, Any]] = None
                existing_entry = existing_tasks_by_id.get(task["id"])

                if existing_entry:
                    node_id, node_data = existing_entry
                    updated_node = dict(node_data)
                    labels = updated_node.get("labels") or ["Task"]
                    updated = False
                    for key, value in task_payload.items():
                        if (
                            value not in (None, "", [], {})
                            and updated_node.get(key) != value
                        ):
                            updated_node[key] = value
                            updated = True
                    if updated and node_id:
                        self.db._save_node(node_id, labels, updated_node)
                        node_data = updated_node
                else:
                    node_id = self.db.create_node("Task", task_payload)
                    if node_id:
                        task_count += 1
                        node_data = self.db.get_node(node_id)

                if node_id and node_data:
                    existing_tasks_by_id[task["id"]] = (node_id, node_data)
                    task_node_map[task["id"]] = node_id

            taxonomy_links = 0
            for task in loader.tasks:
                match_payload = task.get("taxonomy_match")
                if not match_payload:
                    continue

                match_result = TaskMatchResult(
                    match=dict(match_payload),
                    method=match_payload.get("match_method", "taxonomy_rule"),
                    fallback_node_id=match_payload.get("_fallback_node_id"),
                )
                canonical_node_id = task_resolver.ensure_canonical_task(match_result)
                if not canonical_node_id:
                    continue

                task_uid_value = task.get("task_uid")
                if not task_uid_value:
                    continue
                task_node_key = f"neurostore_task:{task_uid_value}"
                source_node_id = task_node_map.get(task_node_key)
                if not source_node_id:
                    continue

                rel_properties = {
                    "source": "neurostore_taxonomy",
                    "match_method": match_payload.get("match_method"),
                    "confidence": match_payload.get("confidence"),
                }
                if match_payload.get("canonical_id"):
                    rel_properties["canonical_id"] = match_payload["canonical_id"]
                if match_payload.get("parameters"):
                    rel_properties["parameters"] = match_payload["parameters"]

                if self._create_relationship_safe(
                    source_node_id,
                    canonical_node_id,
                    "MAPS_TO",
                    rel_properties,
                ):
                    taxonomy_links += 1

            if taxonomy_links:
                logger.info(
                    "Linked %d Neurostore tasks to canonical taxonomy tasks",
                    taxonomy_links,
                )

            taxonomy_linker = self._get_taxonomy_linker()
            taxonomy_suggested = 0
            concept_exists_cache: Dict[str, bool] = {}

            def _concept_exists(concept_id: str) -> bool:
                if concept_id not in concept_exists_cache:
                    concept_exists_cache[concept_id] = bool(
                        self.db.find_nodes("Concept", {"id": concept_id})
                    )
                return concept_exists_cache[concept_id]

            if taxonomy_linker:
                for task in loader.tasks:
                    task_uid_value = task.get("task_uid")
                    if not task_uid_value:
                        continue
                    task_node_key = f"neurostore_task:{task_uid_value}"
                    source_node_id = task_node_map.get(task_node_key)
                    if not source_node_id:
                        continue
                    suggestions = taxonomy_linker.suggestions_for_task(task)
                    if not suggestions:
                        continue
                    for suggestion in suggestions:
                        concept_id = suggestion.concept_id
                        if not concept_id or not _concept_exists(concept_id):
                            continue
                        props = self._flatten_properties(
                            suggestion.relationship_properties()
                        )
                        if self._create_relationship_safe(
                            source_node_id,
                            concept_id,
                            "SUGGESTS_MEASURES",
                            props,
                        ):
                            taxonomy_suggested += 1

            if taxonomy_suggested:
                logger.info(
                    "Added %d taxonomy-derived SUGGESTS_MEASURES edges",
                    taxonomy_suggested,
                )

            metadata_linker = NeurostoreTaskLinker(self.db)
            metadata_stats = metadata_linker.link_tasks(loader.tasks, task_node_map)
            if metadata_stats.get("concept_links") or metadata_stats.get(
                "domain_links"
            ):
                logger.info(
                    "Linked Neurostore metadata to concepts (%d) and domains (%d)",
                    metadata_stats.get("concept_links", 0),
                    metadata_stats.get("domain_links", 0),
                )

            def _persist_relationships(
                items: List[Dict[str, Any]],
                start_map: Dict[str, str],
            ) -> None:
                nonlocal relationship_count
                for relationship in items:
                    start_id = start_map.get(relationship["start"])
                    end_id = task_node_map.get(relationship["end"])
                    if not start_id or not end_id:
                        continue
                    try:
                        rel_props = self._flatten_properties(
                            dict(relationship.get("properties") or {})
                        )
                        rel_id = self.db.create_relationship(
                            start_id,
                            end_id,
                            relationship.get("type", relationship_type),
                            rel_props,
                        )
                        if rel_id:
                            relationship_count += 1
                    except Exception as exc:
                        logger.debug(
                            "Skipping Neurostore relationship %s -> %s: %s",
                            start_id,
                            end_id,
                            exc,
                        )

            _persist_relationships(collection_relationships, collection_node_map)
            _persist_relationships(publication_relationships, publication_node_map)

            link_stats = self._link_neurostore_metadata(link_tasks=use_embedding_linker)

            stats = loader.get_statistics()
            stats.update(
                {
                    "publications_created": publication_count,
                    "collections_created": collection_count,
                    "tasks_created": task_count,
                    "relationships_created": relationship_count,
                    "taxonomy_links": taxonomy_links,
                    "metadata_concept_links": metadata_stats.get("concept_links", 0),
                    "metadata_domain_links": metadata_stats.get("domain_links", 0),
                    "metadata_concept_misses": metadata_stats.get("concept_misses", 0),
                    "metadata_domain_misses": metadata_stats.get("domain_misses", 0),
                    "concept_links": link_stats.get("concept_links", 0),
                    "domain_links": link_stats.get("domain_links", 0),
                    "mapsto_links": link_stats.get("mapsto_links", 0),
                }
            )

            auto_meta_cfg = config.get("auto_scholarly_metadata", {})
            if auto_meta_cfg.get("enabled", True):
                meta_stats = self._ensure_scholarly_metadata(
                    dois_for_metadata, auto_meta_cfg
                )
                if meta_stats:
                    stats["scholarly_metadata"] = meta_stats

            logger.info(f"Loaded Neurostore: {stats}")
            self.stats["sources_loaded"].append("neurostore")
            return stats

        except Exception as exc:
            logger.error(f"Failed to load Neurostore: {exc}")
            self.stats["errors"].append(f"neurostore: {exc}")
            return {"error": str(exc)}

    def load_allen_hba(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """Hydrate Allen Human Brain Atlas expression spine data."""

        logger.info("Loading Allen HBA expression metadata...")
        config = config or {}
        mode = (mode or "spine").lower()

        if mode == "on_demand":
            adapter = AllenHBAAdapter(config)
            ttl = config.get("cache_ttl_sec")
            self.ondemand.register("allen_hba", adapter, ttl_seconds=ttl)
            return {"mode": "on_demand", "registered": True}

        manifest_path = config.get("manifest_path")
        if not manifest_path:
            raise ValueError("allen_hba.manifest_path is required when mode='spine'")

        max_topk = int(config.get("topk_per_region", 100))
        loader = AllenHBALoader(Path(manifest_path), max_genes_per_region=max_topk)

        profile_stats = upsert_expression_spine(
            self.db,
            loader,
            max_genes_per_region=max_topk,
        )

        profile_stats.update(
            {
                "mode": mode,
                "manifest_path": str(Path(manifest_path).resolve()),
            }
        )

        logger.info("Loaded Allen HBA expression spine: %s", profile_stats)
        self.stats["sources_loaded"].append("allen_hba")
        return profile_stats

    def load_allen_ccfv3(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """Hydrate the Allen CCFv3 atlas hierarchy into BR-KG."""

        logger.info("Loading Allen CCFv3 atlas hierarchy...")
        config = config or {}
        cache_dir = config.get("cache_dir")
        structure_ids = config.get("structure_ids")
        if isinstance(structure_ids, str):
            structure_ids = [
                int(token.strip())
                for token in structure_ids.split(",")
                if token.strip()
            ]

        loader = AllenBrainUnifiedLoader(cache_dir=cache_dir)
        atlas_summary = loader.load_atlas_hierarchy(structure_ids=structure_ids)
        payload = loader.export_for_kg()

        if (
            self.db
            and hasattr(self.db, "create_node")
            and hasattr(self.db, "create_relationship")
        ):
            for node in payload.get("nodes", []):
                node_id = node.get("id")
                if node_id is None:
                    continue
                node_type = node.get("type") or "Entity"
                props = dict(node.get("properties") or {})
                props.setdefault("id", node_id)
                self.db.create_node(node_type, props, node_id=str(node_id))

            for edge in payload.get("edges", []):
                source = edge.get("source")
                target = edge.get("target")
                rel_type = edge.get("type")
                if source is None or target is None or not rel_type:
                    continue
                self.db.create_relationship(
                    str(source),
                    str(target),
                    str(rel_type),
                    dict(edge.get("properties") or {}),
                )

        stats = {
            "mode": mode,
            "atlas": atlas_summary.get("atlas", "AllenCCFv3"),
            "structures_count": atlas_summary.get("structures_count", 0),
            "nodes_exported": len(payload.get("nodes", [])),
            "edges_exported": len(payload.get("edges", [])),
            "cache_dir": str(Path(loader.cache_dir).resolve()),
            "structure_filter_applied": bool(structure_ids),
        }
        logger.info("Loaded Allen CCFv3 atlas: %s", stats)
        self.stats["sources_loaded"].append("allen_ccfv3")
        return stats

    def load_virtual_brain(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """Hydrate Virtual Brain simulation metadata."""

        logger.info("Loading Virtual Brain simulations...")
        config = config or {}
        mode = (mode or "spine").lower()

        if mode == "on_demand":
            registration = self._register_on_demand_source("virtual_brain", config)
            return registration or {"mode": "on_demand", "registered": False}

        cache_dir = Path(config.get("cache_dir", "data/virtual_brain/cache"))
        topk = int(config.get("topk_regions", 20))
        loader = VirtualBrainLoader(cache_dir, topk_regions=topk)

        stats = loader.ingest(self.db)
        stats.update(
            {
                "cache_dir": str(cache_dir.resolve()),
                "topk_regions": topk,
                "mode": "spine",
            }
        )

        logger.info("Loaded Virtual Brain simulations: %s", stats)
        self.stats["sources_loaded"].append("virtual_brain")
        return stats

    def load_neurobagel(
        self, config: Dict[str, Any] = None, mode: str = "full"
    ) -> Dict[str, Any]:
        """
        Load Neurobagel phenotype data and link subjects to phenotype records.
        """
        logger.info("Loading Neurobagel phenotypes...")
        config = config or {}
        mode = (mode or "full").lower()
        logger.info("Neurobagel raw config: %s", config)

        try:
            ingest_mode = config.get("mode", "public").lower()

            if ingest_mode == "public":
                loader_config = {
                    "include_nodes": config.get("include_nodes"),
                    "exclude_nodes": config.get("exclude_nodes"),
                    "dataset_limit_per_node": config.get("dataset_limit_per_node"),
                    "batch_size": config.get("batch_size"),
                    "offline_cache_dir": config.get("offline_cache_dir"),
                }
                nodes_endpoint = config.get("nodes_endpoint")
                if nodes_endpoint:
                    loader_config["nodes_endpoint"] = nodes_endpoint
                logger.info("Neurobagel public loader config: %s", loader_config)
                stats = load_neurobagel_public(self.db, loader_config)
            else:
                tsv_path = config.get("tsv_path")
                if not tsv_path:
                    cache_dir = config.get("cache_dir", "data/neurokg/raw/neurobagel")
                    use_cache = config.get("use_cache", True)
                    tsv_path = fetch_neurobagel_data(cache_dir, use_cache=use_cache)

                stats = load_neurobagel_data(self.db, tsv_path)
                if stats.get("errors"):
                    logger.warning(
                        "Neurobagel loader reported issues: %s", stats["errors"]
                    )

            self.stats["sources_loaded"].append("neurobagel")
            return stats

        except Exception as exc:
            logger.error("Failed to load Neurobagel phenotypes: %s", exc, exc_info=True)
            self.stats["errors"].append(f"neurobagel: {exc}")
            return {"error": str(exc)}

    def load_scholarly_metadata(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """
        Load Crossref/OpenAlex/ORCID/ROR style scholarly metadata.
        """
        logger.info("Loading scholarly metadata (Crossref/OpenAlex/ORCID/ROR)...")
        config = config or {}

        # Skip if explicitly disabled or no harvest parameters provided
        if config.get("enabled") is False:
            logger.info("Scholarly metadata loader disabled via config.")
            return {"skipped": True, "reason": "disabled"}

        try:
            dois = config.get("dois") or config.get("doi_list")
            if isinstance(dois, str):
                dois = [item.strip() for item in dois.split(",") if item.strip()]
            openalex_filter = config.get("openalex_filter")
            metadata_path = (
                config.get("metadata_path")
                or config.get("metadata_file")
                or config.get("path")
            )

            if not metadata_path and not dois and not openalex_filter:
                logger.info(
                    "No DOI list, OpenAlex filter, or metadata file provided; skipping scholarly metadata ingest."
                )
                return {"skipped": True, "reason": "no-harvest-parameters"}

            loader = ScholarlyMetadataLoader(
                cache_dir=config.get("cache_dir"),
                http_timeout=config.get("http_timeout", 20),
                crossref_mailto=config.get("crossref_mailto"),
            )
            stats = loader.ingest(
                self.db,
                metadata_path=metadata_path,
                dois=dois,
                openalex_filter=openalex_filter,
            )
            if stats.get("errors"):
                logger.warning(
                    "Scholarly metadata loader reported issues: %s", stats["errors"]
                )

            self.stats["sources_loaded"].append("scholarly_metadata")
            return stats

        except Exception as exc:
            logger.error("Failed to load scholarly metadata: %s", exc, exc_info=True)
            self.stats["errors"].append(f"scholarly_metadata: {exc}")
            return {"error": str(exc)}

    def load_nidm_results(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, Any]:
        """
        Load NIDM-Results statistical maps and provenance.
        """
        logger.info("Loading NIDM-Results archives...")
        config = config or {}

        if config.get("enabled") is False:
            logger.info("NIDM-Results loader disabled via config.")
            return {"skipped": True, "reason": "disabled"}

        try:
            loader = NIDMResultsLoader(
                cache_dir=config.get("cache_dir"),
                http_timeout=config.get("http_timeout", 30),
            )
            nidm_paths = config.get("nidm_paths")
            if isinstance(nidm_paths, str):
                nidm_paths = [p.strip() for p in nidm_paths.split(",") if p.strip()]

            nidm_urls = config.get("nidm_urls")
            if isinstance(nidm_urls, str):
                nidm_urls = [u.strip() for u in nidm_urls.split(",") if u.strip()]

            if not (nidm_paths or nidm_urls):
                logger.info("No NIDM manifests provided; skipping NIDM ingest.")
                return {"skipped": True, "reason": "no-manifests-provided"}

            stats = loader.ingest(
                self.db,
                nidm_paths=nidm_paths
                or ([config.get("nidm_path")] if config.get("nidm_path") else None)
                or (
                    [config.get("results_path")] if config.get("results_path") else None
                )
                or ([config.get("path")] if config.get("path") else None),
                nidm_urls=nidm_urls,
            )
            if stats.get("errors"):
                logger.warning(
                    "NIDM-Results loader reported issues: %s", stats["errors"]
                )

            self.stats["sources_loaded"].append("nidm_results")
            return stats

        except Exception as exc:
            logger.error("Failed to load NIDM-Results archives: %s", exc, exc_info=True)
            self.stats["errors"].append(f"nidm_results: {exc}")
            return {"error": str(exc)}

    # The following loaders exist purely to support on-demand registration.
    def load_neuroquery(
        self, config: Dict[str, Any] = None, mode: str = "on_demand"
    ) -> Dict[str, Any]:
        return {"mode": mode, "warning": "neuroquery is on-demand only"}

    def load_nimare(
        self, config: Dict[str, Any] = None, mode: str = "on_demand"
    ) -> Dict[str, Any]:
        return {"mode": mode, "warning": "nimare is on-demand only"}

    def load_neuroscout(
        self, config: Dict[str, Any] = None, mode: str = "on_demand"
    ) -> Dict[str, Any]:
        return {"mode": mode, "warning": "neuroscout is on-demand only"}

    def load_nilearn_atlases(
        self, config: Dict[str, Any] = None, mode: str = "full"
    ) -> Dict[str, Any]:
        """
        Load common Nilearn parcellation atlases into BR-KG.
        """
        logger.info("Loading Nilearn atlases...")
        config = config or {}
        mode = (mode or "full").lower()

        try:
            data_dir = config.get("data_dir", "data/neurokg/raw/nilearn_atlases")
            atlas_specs = config.get("atlases")

            loader = NilearnAtlasUnifiedLoader(
                atlas_specs=atlas_specs,
                data_dir=data_dir,
            )

            loader.load_regions()
            stats = loader.ingest(self.db)

            logger.info(
                "Loaded Nilearn atlases: %d regions created (skipped %d)",
                stats.get("regions_created", 0),
                stats.get("regions_skipped", 0),
            )
            logger.info(
                "Parcellations created %d (skipped %d); TemplateSpaces created %d (skipped %d)",
                stats.get("parcellations_created", 0),
                stats.get("parcellations_skipped", 0),
                stats.get("template_spaces_created", 0),
                stats.get("template_spaces_skipped", 0),
            )
            logger.info(
                "DataResources created %d (skipped %d)",
                stats.get("resources_created", 0),
                stats.get("resources_skipped", 0),
            )
            if stats.get("failures"):
                logger.warning(
                    "Some Nilearn atlases failed to load: %s", stats["failures"]
                )

            self.stats["sources_loaded"].append("nilearn_atlases")
            return stats

        except Exception as exc:
            logger.error(f"Failed to load Nilearn atlases: {exc}")
            self.stats["errors"].append(f"nilearn_atlases: {exc}")
            return {"error": str(exc)}

    def load_bids(
        self, config: Dict[str, Any] = None, mode: str = "spine"
    ) -> Dict[str, int]:
        """
        Load and validate BIDS datasets.

        Args:
            config: Configuration with optional keys:
                - dataset_paths: List of paths to BIDS datasets
                - strict_validation: If True, treat warnings as errors
                - extract_metadata: If True, extract dataset metadata

        Returns:
            Statistics about loaded data
        """
        config = config or {}
        dataset_paths = config.get("dataset_paths", [])
        strict_validation = config.get("strict_validation", True)

        if not dataset_paths:
            logger.warning("No BIDS dataset paths provided")
            return {"datasets_processed": 0}

        try:
            # Initialize BIDS loader
            loader = BIDSUnifiedLoader(
                db_path=self.db_path,
                strict_validation=strict_validation,
                cache_results=True,
            )

            # Load datasets
            results = loader.load_batch(dataset_paths)

            # Store validation results in database
            stats = {
                "datasets_processed": len(results),
                "valid_datasets": sum(
                    1 for r in results.values() if r.get("is_valid", False)
                ),
                "invalid_datasets": sum(
                    1 for r in results.values() if not r.get("is_valid", True)
                ),
            }

            # Store each validation result
            for dataset_path, result in results.items():
                if "error" not in result:
                    # Create dataset entity
                    dataset_entity = {
                        "type": "BIDSDataset",
                        "path": dataset_path,
                        "name": result.get("dataset_name", Path(dataset_path).name),
                        "bids_version": result.get("bids_version", "Unknown"),
                        "is_valid": result.get("is_valid", False),
                        "n_participants": result.get("n_participants", 0),
                        "tasks": result.get("tasks", []),
                        "modalities": result.get("modalities", []),
                        "quality_score": result.get("summary", {}).get(
                            "quality_score", 0
                        ),
                        "validation_time": result.get("timestamp"),
                    }

                    # Store in database
                    if self.db:
                        self.db.add_node(dataset_entity, "BIDSDataset")

            # Update global stats
            self.stats["sources_loaded"].append("bids")
            self.stats["total_entities"] += stats["datasets_processed"]

            logger.info(f"Loaded BIDS datasets: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Failed to load BIDS datasets: {e}")
            self.stats["errors"].append(f"bids: {e}")
            return {"error": str(e)}

    def create_cross_source_links(self) -> Dict[str, int]:
        """
        Create links between entities from different sources.

        Returns:
            Statistics about created links
        """
        logger.info("Creating cross-source links...")

        try:
            from brain_researcher.services.neurokg.etl.mappers.cross_source_linker import (
                CrossSourceLinker,
            )

            linker = CrossSourceLinker(self.db)
            # Link nodes from all loaded sources
            link_stats = {}
            for source in self.stats.get("sources_loaded", []):
                count = linker.link_after_source_load(source)
                link_stats[source] = count
            stats = {"links_created": sum(link_stats.values()), "by_source": link_stats}

            logger.info(f"Created cross-source links: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Failed to create cross-source links: {e}")
            self.stats["errors"].append(f"cross_source_links: {e}")
            return {"error": str(e)}

    def load_all(
        self, sources: Optional[List[str]] = None, config: Dict[str, Any] = None
    ):
        """Load all or a subset of data sources according to ingestion modes."""

        config = config or {}

        all_sources = {
            "cognitive_atlas": self.load_cognitive_atlas,
            "pubmed": self.load_pubmed,
            "neurosynth": self.load_neurosynth,
            "neurovault": self.load_neurovault,
            "openneuro": self.load_openneuro,
            "openneuro_glmfitlins": self.load_openneuro_glmfitlins,
            "wikidata": self.load_wikidata,
            "neuromaps": self.load_neuromaps,
            "nilearn_atlases": self.load_nilearn_atlases,
            "niclip": self.load_niclip_embeddings,
            "brainmap": self.load_brainmap,
            "neurostore": self.load_neurostore,
            "gabriel": self.load_gabriel,
            "neurobagel": self.load_neurobagel,
            "scholarly_metadata": self.load_scholarly_metadata,
            "nidm_results": self.load_nidm_results,
            "bids": self.load_bids,
            "neuroquery": self.load_neuroquery,
            "nimare": self.load_nimare,
            "neuroscout": self.load_neuroscout,
            "onvoc": self.load_onvoc,
            "allen_hba": self.load_allen_hba,
            "allen_ccfv3": self.load_allen_ccfv3,
            "virtual_brain": self.load_virtual_brain,
        }

        if sources:
            sources_to_iterate = {k: v for k, v in all_sources.items() if k in sources}
        else:
            sources_to_iterate = all_sources

        sources_cfg = config.get("sources", {})
        if not sources_cfg:
            # Legacy compatibility: allow using top-level keys per source
            sources_cfg = {
                name: config.get(name, {})
                for name in sources_to_iterate.keys()
                if name in config
            }

        results: Dict[str, Any] = {}
        sources_with_graph_ingest: set[str] = set()

        for source_name, loader_func in sources_to_iterate.items():
            source_cfg = dict(sources_cfg.get(source_name, {}))
            mode = source_cfg.get("mode", self._default_mode_for(source_name))
            ingest_to_graph = source_cfg.get("ingest_to_graph", True)

            if mode == "on_demand":
                registration = self._register_on_demand_source(source_name, source_cfg)
                if registration:
                    results[source_name] = registration
                continue

            logger.info("Loading %s in %s mode...", source_name, mode)
            result_payload = loader_func(source_cfg, mode=mode)
            results[source_name] = {"mode": mode, "result": result_payload}
            if ingest_to_graph:
                sources_with_graph_ingest.add(source_name)

        if config.get("create_links", True):
            if not sources_with_graph_ingest:
                logger.info(
                    "Skipping cross-source links (no graph ingestion enabled for this run).",
                )
            else:
                results["cross_source_links"] = self.create_cross_source_links()

        self.stats["end_time"] = datetime.now()
        self.stats["duration"] = str(self.stats["end_time"] - self.stats["start_time"])

        if self.db:
            db_stats = self.db.get_stats()
            self.stats["total_entities"] = db_stats.get("total_nodes", 0)
            self.stats["total_relationships"] = db_stats.get("total_relationships", 0)

        results["on_demand_sources"] = list(self.ondemand.available().keys())

        self._record_ingestion_run(
            results=results,
            config=config,
            sources=sources_to_iterate.keys(),
        )

        return {"results": results, "statistics": self.stats}

    def close(self):
        """Close database connection."""
        if self.db:
            self.db.close()
            logger.info("Database connection closed")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Load neuroimaging data into BR-KG")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=[
            "cognitive_atlas",
            "pubmed",
            "neurosynth",
            "neurovault",
            "openneuro",
            "openneuro_glmfitlins",
            "wikidata",
            "neuromaps",
            "nilearn_atlases",
            "niclip",
            "brainmap",
            "neurostore",
            "gabriel",
            "bids",
            "allen_ccfv3",
            "virtual_brain",
        ],
        help="Specific sources to load (default: all)",
    )
    parser.add_argument("--config", type=str, help="Path to configuration JSON file")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Deprecated SQLite path (ignored). Neo4j credentials are required.",
    )
    parser.add_argument(
        "--full", action="store_true", help="Load full datasets (not just samples)"
    )
    parser.add_argument(
        "--no-links", action="store_true", help="Skip creating cross-source links"
    )

    args = parser.parse_args()

    # Load configuration
    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    # Override with command line arguments
    if args.full:
        config["full_load"] = True
    if args.no_links:
        config["create_links"] = False

    # Create loader and load data
    if args.db:
        print(
            "⚠️  --db is ignored; Neo4j is required. Set NEO4J_URI/NEO4J_PASSWORD instead.",
            file=sys.stderr,
        )
    loader = MasterDataLoader(db_path=None)

    try:
        results = loader.load_all(sources=args.sources, config=config)

        # Print results
        print("\n" + "=" * 60)
        print("DATA INGESTION COMPLETE")
        print("=" * 60)

        print("\nSources Loaded:")
        for source in results["statistics"]["sources_loaded"]:
            print(f"  ✓ {source}")

        print("\nStatistics:")
        print(f"  Total Entities: {results['statistics']['total_entities']:,}")
        print(
            f"  Total Relationships: {results['statistics']['total_relationships']:,}"
        )
        print(f"  Duration: {results['statistics']['duration']}")

        if results["statistics"]["errors"]:
            print("\nErrors:")
            for error in results["statistics"]["errors"]:
                print(f"  ✗ {error}")

        print("\nDetailed Results:")
        print(json.dumps(results["results"], indent=2))

    finally:
        loader.close()


if __name__ == "__main__":
    main()
