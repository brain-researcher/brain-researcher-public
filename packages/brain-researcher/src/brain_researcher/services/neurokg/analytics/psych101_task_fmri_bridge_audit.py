"""Audit how far Psych-101 tasks currently bridge into task-fMRI graph layers."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Psych101TaskFmriBridgeAuditConfig:
    """Configuration for Psych-101 to task-fMRI bridge audits."""

    experiment_limit: int = 250


def run_psych101_task_fmri_bridge_audit(
    db: Any,
    *,
    config: Psych101TaskFmriBridgeAuditConfig = Psych101TaskFmriBridgeAuditConfig(),
) -> dict[str, Any]:
    """Run a read-only bridge audit against Neo4j/graph DB."""
    summary_counts = {
        "dataset_count": _single_value(
            db,
            "MATCH (d:Dataset) RETURN count(DISTINCT d) AS value",
        ),
        "dataset_task_edge_count": _single_value(
            db,
            "MATCH (:Dataset)-[r:HAS_TASK|USES_TASK]->(:Task) RETURN count(r) AS value",
        ),
        "task_analysis_count": _single_value(
            db,
            "MATCH (ta:TaskAnalysis) RETURN count(DISTINCT ta) AS value",
        ),
        "contrast_count": _single_value(
            db,
            "MATCH (c:Contrast) RETURN count(DISTINCT c) AS value",
        ),
        "stats_map_count": _single_value(
            db,
            "MATCH (m:StatsMap) RETURN count(DISTINCT m) AS value",
        ),
        "stats_map_in_region_edge_count": _single_value(
            db,
            "MATCH (:StatsMap)-[r:IN_REGION]->(:BrainRegion) RETURN count(r) AS value",
        ),
        "psych101_experiment_count": _single_value(
            db,
            "MATCH (e:Psych101Experiment) RETURN count(DISTINCT e) AS value",
        ),
        "psych101_uses_task_edge_count": _single_value(
            db,
            "MATCH (:Psych101Experiment)-[r:USES_TASK]->(:Task) RETURN count(r) AS value",
        ),
    }
    overlap = {
        "direct_shared_dataset_task_count": _single_value(
            db,
            """
            MATCH (:Psych101Experiment)-[:USES_TASK]->(t:Task)<-[:HAS_TASK|USES_TASK]-(:Dataset)
            RETURN count(DISTINCT t) AS value
            """,
        ),
        "canonical_shared_dataset_task_count": _single_value(
            db,
            """
            MATCH (:Psych101Experiment)-[:USES_TASK]->(:Task)-[:MAPS_TO]->(t:Task)<-[:HAS_TASK|USES_TASK]-(:Dataset)
            RETURN count(DISTINCT t) AS value
            """,
        ),
        "canonical_task_analysis_count": _single_value(
            db,
            """
            MATCH (:Psych101Experiment)-[:USES_TASK]->(:Task)-[:MAPS_TO]->(t:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)
            RETURN count(DISTINCT ta) AS value
            """,
        ),
        "family_task_analysis_count": _single_value(
            db,
            """
            MATCH (:Psych101Experiment)-[:USES_TASK]->(:Task)-[:BELONGS_TO_FAMILY]->(:TaskFamily)
                  <-[:BELONGS_TO_FAMILY]-(:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)
            RETURN count(DISTINCT ta) AS value
            """,
        ),
    }
    experiment_rows = _query_rows(
        db,
        """
        MATCH (e:Psych101Experiment)
        CALL {
          WITH e
          OPTIONAL MATCH (e)-[:USES_TASK]->(lt:Task)
          OPTIONAL MATCH (lt)-[:MAPS_TO]->(ct:Task)
          OPTIONAL MATCH (ct)<-[:MAPS_TO]-(ta:TaskAnalysis)<-[:GENERATED_FROM]-(m:StatsMap)
          OPTIONAL MATCH (m)-[:DERIVED_FROM]->(c:Contrast)
          OPTIONAL MATCH (m)-[:IN_REGION]->(r:BrainRegion)
          RETURN
            collect(DISTINCT lt.id) AS local_task_ids,
            collect(DISTINCT lt.name) AS local_task_names,
            collect(DISTINCT ct.id) AS canonical_task_ids,
            collect(DISTINCT ct.name) AS canonical_task_names,
            count(DISTINCT ta) AS canonical_task_analysis_hits,
            count(DISTINCT c) AS canonical_contrast_hits,
            count(DISTINCT r) AS canonical_brain_region_hits
        }
        CALL {
          WITH e
          OPTIONAL MATCH (e)-[:USES_TASK]->(lt:Task)-[:BELONGS_TO_FAMILY]->(f:TaskFamily)
                        <-[:BELONGS_TO_FAMILY]-(ct:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)
                        <-[:GENERATED_FROM]-(m:StatsMap)
          OPTIONAL MATCH (m)-[:DERIVED_FROM]->(c:Contrast)
          OPTIONAL MATCH (m)-[:IN_REGION]->(r:BrainRegion)
          RETURN
            collect(DISTINCT f.id) AS family_ids,
            collect(DISTINCT f.name) AS family_names,
            count(DISTINCT ta) AS family_task_analysis_hits,
            count(DISTINCT c) AS family_contrast_hits,
            count(DISTINCT r) AS family_brain_region_hits
        }
        RETURN
          e.id AS experiment_id,
          coalesce(e.name, e.title, e.id) AS experiment_name,
          local_task_ids,
          local_task_names,
          canonical_task_ids,
          canonical_task_names,
          family_ids,
          family_names,
          canonical_task_analysis_hits,
          canonical_contrast_hits,
          canonical_brain_region_hits,
          family_task_analysis_hits,
          family_contrast_hits,
          family_brain_region_hits
        ORDER BY experiment_id
        LIMIT $limit
        """,
        {"limit": int(config.experiment_limit)},
    )
    experiments = []
    for row in experiment_rows:
        experiment = {
            "experiment_id": row.get("experiment_id"),
            "experiment_name": row.get("experiment_name"),
            "local_task_ids": _clean_text_list(row.get("local_task_ids")),
            "local_task_names": _clean_text_list(row.get("local_task_names")),
            "canonical_task_ids": _clean_text_list(row.get("canonical_task_ids")),
            "canonical_task_names": _clean_text_list(
                row.get("canonical_task_names")
            ),
            "family_ids": _clean_text_list(row.get("family_ids")),
            "family_names": _clean_text_list(row.get("family_names")),
            "canonical_task_analysis_hits": int(
                row.get("canonical_task_analysis_hits") or 0
            ),
            "canonical_contrast_hits": int(row.get("canonical_contrast_hits") or 0),
            "canonical_brain_region_hits": int(
                row.get("canonical_brain_region_hits") or 0
            ),
            "family_task_analysis_hits": int(
                row.get("family_task_analysis_hits") or 0
            ),
            "family_contrast_hits": int(row.get("family_contrast_hits") or 0),
            "family_brain_region_hits": int(
                row.get("family_brain_region_hits") or 0
            ),
        }
        experiment["bridge_status"] = _bridge_status(experiment)
        experiments.append(experiment)

    status_counts: dict[str, int] = {}
    for row in experiments:
        status = row["bridge_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "config": {"experiment_limit": int(config.experiment_limit)},
        "summary": {
            **summary_counts,
            "overlap": overlap,
            "bridge_status_counts": status_counts,
        },
        "experiments": experiments,
    }


def write_psych101_task_fmri_bridge_audit_artifacts(
    result: dict[str, Any],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write audit summary and per-experiment table to disk."""
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = out_dir / "summary.json"
    experiments_tsv_path = out_dir / "experiment_bridge_audit.tsv"

    summary_path.write_text(
        json.dumps(result.get("summary") or {}, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "experiment_id",
        "experiment_name",
        "bridge_status",
        "local_task_ids",
        "canonical_task_ids",
        "family_ids",
        "canonical_task_analysis_hits",
        "canonical_contrast_hits",
        "canonical_brain_region_hits",
        "family_task_analysis_hits",
        "family_contrast_hits",
        "family_brain_region_hits",
    ]
    with experiments_tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in result.get("experiments") or []:
            payload = dict(row)
            payload["local_task_ids"] = "|".join(row.get("local_task_ids") or [])
            payload["canonical_task_ids"] = "|".join(
                row.get("canonical_task_ids") or []
            )
            payload["family_ids"] = "|".join(row.get("family_ids") or [])
            writer.writerow({key: payload.get(key) for key in fieldnames})

    return {
        "summary_json": str(summary_path),
        "experiment_bridge_audit_tsv": str(experiments_tsv_path),
    }


def _bridge_status(experiment: dict[str, Any]) -> str:
    if int(experiment.get("canonical_task_analysis_hits") or 0) > 0:
        return "canonical_bridge_ready"
    if int(experiment.get("family_task_analysis_hits") or 0) > 0:
        return "family_bridge_ready"
    if experiment.get("canonical_task_ids") or experiment.get("family_ids"):
        return "ontology_bridge_only"
    if experiment.get("local_task_ids"):
        return "local_only"
    return "no_task_link"


def _single_value(db: Any, query: str, params: dict[str, Any] | None = None) -> int:
    rows = _query_rows(db, query, params)
    if not rows:
        return 0
    return int(rows[0].get("value") or 0)


def _query_rows(
    db: Any,
    query: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = params or {}
    if hasattr(db, "execute_query"):
        return [dict(row) for row in db.execute_query(query, payload)]
    if hasattr(db, "_run"):
        return [dict(row) for row in db._run(query, payload)]
    raise TypeError("db must expose execute_query() or _run()")


def _clean_text_list(values: Any) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in cleaned:
            continue
        cleaned.append(text)
    return cleaned
