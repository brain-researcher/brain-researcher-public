#!/usr/bin/env python3
"""
NIDM-Results Loader
-------------------

Consumes NIDM-Results JSON manifests (either local files or remote URLs) and
registers `StatisticalMap` nodes along with provenance relationships in NeoKG.

Expected JSON structure (list of dicts):
{
  "stat_map_id": "nidm:map:0001",
  "label": "Contrast 1 Z",
  "uri": "file:///path/to/map.nii.gz",
  "space": "MNI152NLin2009cAsym",
  "modality": "fMRI",
  "experiment_type": "task",
  "threshold": {"type": "p-value", "value": 0.001, "correction": "FWE"},
  "software": {"name": "SPM12", "version": "12.3"},
  "derived_from": {"publication_doi": "10.1234/example.2025.001", "contrast_id": "contrast:example"},
  "atlas_overlaps": [{"region_id": "schaefer2018_200_17n_2mm:L_FPC", "overlap": 0.42}]
}
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/br-kg/raw/nidm")
DEFAULT_HTTP_TIMEOUT = 30


def _read_results(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"NIDM results file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


class NIDMResultsLoader:
    """Parses NIDM result summaries and writes nodes/edges to the graph."""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        http_timeout: int = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http_timeout = http_timeout

    def load_entries(
        self,
        *,
        nidm_paths: Optional[Sequence[str]] = None,
        nidm_urls: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        if nidm_paths:
            for path in nidm_paths:
                entries.extend(_read_results(Path(path)))

        if nidm_urls:
            for url in nidm_urls:
                cache_file = self._download_to_cache(url)
                entries.extend(_read_results(cache_file))

        if not entries:
            raise ValueError(
                "NIDMResultsLoader requires `nidm_paths` or `nidm_urls` with JSON/NDJSON manifests."
            )

        logger.info("Loaded %d NIDM result records", len(entries))
        return entries

    def ingest(
        self,
        db,
        entries: Optional[Iterable[Dict[str, Any]]] = None,
        **load_kwargs: Any,
    ) -> Dict[str, Any]:
        records = (
            list(entries) if entries is not None else self.load_entries(**load_kwargs)
        )
        stats = {
            "stat_maps_upserted": 0,
            "derived_from_edges": 0,
            "software_edges": 0,
            "region_overlap_edges": 0,
            "errors": [],
        }

        for record in records:
            try:
                self._ingest_single(db, record, stats)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to ingest NIDM record %s", record.get("stat_map_id")
                )
                stats["errors"].append(
                    {"stat_map_id": record.get("stat_map_id"), "error": str(exc)}
                )

        return stats

    def make_adapter(self, base_kwargs: Optional[Dict[str, Any]] = None):
        return NIDMResultsAdapter(self, base_kwargs or {})

    def _download_to_cache(self, url: str) -> Path:
        filename = url.split("/")[-1] or f"nidm_{int(time.time())}.json"
        cache_path = self.cache_dir / filename
        if cache_path.exists():
            return cache_path

        response = requests.get(url, timeout=self.http_timeout)
        response.raise_for_status()
        cache_path.write_bytes(response.content)
        logger.info("Downloaded NIDM manifest %s", cache_path)
        return cache_path

    def _ingest_single(self, db, record: Dict[str, Any], stats: Dict[str, Any]) -> None:
        stat_map_id = record.get("stat_map_id")
        if not stat_map_id:
            logger.debug("Skipping NIDM record without stat_map_id: %s", record)
            return

        map_props = {
            "id": stat_map_id,
            "label": record.get("label"),
            "uri": record.get("uri"),
            "space": record.get("space"),
            "modality": record.get("modality"),
            "experiment_type": record.get("experiment_type"),
            "threshold": record.get("threshold"),
            "source": "nidm_results",
        }
        db.create_node("StatisticalMap", map_props, node_id=stat_map_id)
        stats["stat_maps_upserted"] += 1

        derived = record.get("derived_from") or {}
        derived_doi = derived.get("publication_doi")
        contrast_id = derived.get("contrast_id")

        if derived_doi:
            pub_props = {
                "id": derived_doi,
                "doi": derived_doi,
                "source": "scholarly_metadata_stub",
            }
            pub_id = db.create_node("Publication", pub_props, node_id=derived_doi)
            rel_props = {"source": "nidm_results"}
            db.create_relationship(stat_map_id, pub_id, "DERIVED_FROM", rel_props)
            stats["derived_from_edges"] += 1

        if contrast_id:
            contrast_props = {"id": contrast_id, "source": "nidm_results_stub"}
            contrast_node = db.create_node(
                "Contrast", contrast_props, node_id=contrast_id
            )
            rel_props = {"source": "nidm_results"}
            db.create_relationship(
                stat_map_id, contrast_node, "DERIVED_FROM_CONTRAST", rel_props
            )

        software = record.get("software") or {}
        software_name = software.get("name")
        if software_name:
            software_version = software.get("version")
            software_id = f"software:{software_name.lower().replace(' ', '-')}"
            software_props = {
                "id": software_id,
                "name": software_name,
                "version": software_version,
                "source": "nidm_results",
            }
            db.create_node("AnalysisSoftware", software_props, node_id=software_id)
            rel_props = {"source": "nidm_results"}
            db.create_relationship(
                stat_map_id, software_id, "PROCESSED_WITH", rel_props
            )
            stats["software_edges"] += 1

        for overlap in record.get("atlas_overlaps", []) or []:
            region_id = overlap.get("region_id")
            if not region_id:
                continue
            region_props = {"id": region_id, "source": "nidm_results_stub"}
            db.create_node("Region", region_props, node_id=region_id)
            rel_props = {
                "source": "nidm_results",
                "overlap": overlap.get("overlap"),
            }
            db.create_relationship(stat_map_id, region_id, "IN_REGION", rel_props)
            stats["region_overlap_edges"] += 1


class NIDMResultsAdapter:
    """Callable adapter to fetch NIDM manifest entries on demand."""

    def __init__(self, loader: NIDMResultsLoader, base_kwargs: Dict[str, Any]) -> None:
        self.loader = loader
        self.base_kwargs = base_kwargs

    def __call__(self, **kwargs: Any) -> List[Dict[str, Any]]:
        params = {**self.base_kwargs, **kwargs}
        return self.loader.load_entries(
            nidm_paths=params.get("nidm_paths"),
            nidm_urls=params.get("nidm_urls"),
        )
