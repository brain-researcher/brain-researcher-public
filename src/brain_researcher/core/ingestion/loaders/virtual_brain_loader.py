"""Loader that hydrates Virtual Brain simulation metadata into BR-KG."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VirtualBrainLoader:
    cache_dir: Path
    topk_regions: int = 20

    def iter_reports(self) -> Iterable[dict[str, Any]]:
        if not self.cache_dir.exists():
            logger.debug(
                "Virtual Brain cache directory %s does not exist", self.cache_dir
            )
            return []

        for report_path in sorted(self.cache_dir.glob("*/report.json")):
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                payload["_report_path"] = str(report_path)
                payload["_cache_dir"] = str(report_path.parent)
                yield payload
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse VB report %s: %s", report_path, exc)
            except OSError as exc:
                logger.warning("Could not read VB report %s: %s", report_path, exc)

    def ensure_virtual_brain_nodes(self, db, report: dict[str, Any]) -> dict[str, int]:
        stats = {
            "simulations_created": 0,
            "simulations_updated": 0,
            "scmatrix_upserts": 0,
            "targetfc_upserts": 0,
            "relationships_created": 0,
            "tasks_missing": 0,
        }
        sim_payload = report.get("simulation") or {}
        sim_id = sim_payload.get("id")
        if not sim_id:
            return stats

        sc_payload = report.get("sc_matrix") or {}
        sc_id = sc_payload.get("id") or sim_payload.get("sc_matrix_id")
        if sc_id and sc_payload:
            sc_props = {
                "id": sc_id,
                "parcellation": sc_payload.get("parcellation"),
                "source": sc_payload.get("source"),
                "license": sc_payload.get("license"),
                "weights_uri": sc_payload.get("weights_uri"),
                "delays_uri": sc_payload.get("delays_uri"),
            }
            db.create_node("SCMatrix", sc_props, node_id=sc_id)  # type: ignore[attr-defined]
            stats["scmatrix_upserts"] += 1

        target_payload = report.get("target_fc") or {}
        target_id = target_payload.get("id")
        if target_id:
            tf_props = {
                "id": target_id,
                "parcellation": target_payload.get("parcellation"),
                "uri": target_payload.get("uri") or target_payload.get("matrix_uri"),
                "n_subjects": target_payload.get("n_subjects"),
                "method": target_payload.get("method"),
                "source": target_payload.get("source"),
            }
            db.create_node("TargetFC", tf_props, node_id=target_id)  # type: ignore[attr-defined]
            stats["targetfc_upserts"] += 1

        region_activity = report.get("region_activity") or []
        if region_activity:
            region_activity = sorted(
                region_activity,
                key=lambda item: item.get("mean_activity", 0.0),
                reverse=True,
            )
            preview = region_activity[: self.topk_regions]
        else:
            preview = []

        simulation_props = dict(sim_payload)
        simulation_props.setdefault("report_uri", report.get("_report_path"))
        simulation_props.setdefault("cache_dir", report.get("_cache_dir"))
        simulation_props["region_activity_preview"] = preview[: min(10, len(preview))]

        existing = db.find_nodes("Simulation", {"id": sim_id})  # type: ignore[attr-defined]
        db.create_node("Simulation", simulation_props, node_id=sim_id)  # type: ignore[attr-defined]
        if existing:
            stats["simulations_updated"] += 1
        else:
            stats["simulations_created"] += 1

        task_id = simulation_props.get("seeded_task_id") or report.get("task_id")
        if task_id:
            if db.find_nodes("Task", {"id": task_id}):  # type: ignore[attr-defined]
                if db.create_relationship(sim_id, task_id, "SEEDED_BY", {"source": "virtual_brain"}):  # type: ignore[attr-defined]
                    stats["relationships_created"] += 1
            else:
                stats["tasks_missing"] += 1

        if sc_id:
            if db.create_relationship(sim_id, sc_id, "USES_NETWORK", {"source": "virtual_brain"}):  # type: ignore[attr-defined]
                stats["relationships_created"] += 1

        if target_id:
            if db.create_relationship(sim_id, target_id, "FIT_TO", {"source": "virtual_brain"}):  # type: ignore[attr-defined]
                stats["relationships_created"] += 1

        return stats

    def ingest(self, db) -> dict[str, int]:
        aggregate = {
            "simulations_created": 0,
            "simulations_updated": 0,
            "scmatrix_upserts": 0,
            "targetfc_upserts": 0,
            "relationships_created": 0,
            "tasks_missing": 0,
            "reports_processed": 0,
        }

        for report in self.iter_reports():
            delta = self.ensure_virtual_brain_nodes(db, report)
            aggregate["reports_processed"] += 1
            for key, value in delta.items():
                aggregate[key] = aggregate.get(key, 0) + value

        return aggregate
