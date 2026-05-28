#!/usr/bin/env python3
"""Ingest GLM multiverse run manifests into Neo4j.

Creates GLMRun, GLMVariant, Artifact, and ResultSummary nodes with relationships:
  (GLMRun)-[:HAS_VARIANT]->(GLMVariant)
  (GLMVariant)-[:PRODUCES]->(Artifact)
  (GLMRun)-[:HAS_SUMMARY]->(ResultSummary)
  (Dataset)-[:HAS_GLM_RUN]->(GLMRun)  (if Dataset node exists)
  (TaskSpec)-[:HAS_GLM_RUN]->(GLMRun) (if TaskSpec node exists)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from brain_researcher.services.neurokg import query_service

logger = logging.getLogger("ingest_glm_run")
logging.basicConfig(level=logging.INFO)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _artifact_id(path: str) -> str:
    return f"artifact:{_sha1(path)}"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except Exception:
        return json.dumps(str(value))


def _find_dataset_node(db, dataset_id: str) -> Optional[str]:
    matches = db.find_nodes("Dataset", {"dataset_id": dataset_id})
    if matches:
        return matches[0][0]
    return None


def _find_task_node(db, dataset_id: str, task: str) -> Optional[str]:
    matches = db.find_nodes("TaskSpec", {"name": task, "dataset": dataset_id})
    if matches:
        return matches[0][0]
    return None


def _ingest_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    dataset_id = data.get("dataset_id")
    task = data.get("task")
    if not dataset_id or not task:
        raise ValueError("run manifest missing dataset_id/task")

    run_id = data.get("run_id") or f"glmrun:{dataset_id}:{task}:{path.parent.name}"
    db = query_service.get_default_db()

    run_props: Dict[str, Any] = {
        "id": run_id,
        "dataset_id": dataset_id,
        "task": task,
        "seed": data.get("seed"),
        "k": data.get("k"),
        "runtime": data.get("runtime"),
        "analysis_level": data.get("analysis_level"),
        "execute": data.get("execute"),
        "created_at": data.get("created_at"),
        "bids_root": data.get("bids_root"),
        "derivatives_root": data.get("derivatives_root"),
        "provenance_path": data.get("provenance_path"),
        "support": data.get("support"),
        "coverage": data.get("coverage"),
        "priors_source": data.get("priors_source"),
        "priors_scope": data.get("priors_scope"),
    }

    run_node = db.create_node("GLMRun", run_props, node_id=run_id)

    dataset_node = _find_dataset_node(db, dataset_id)
    if dataset_node:
        db.create_relationship(dataset_node, run_node, "HAS_GLM_RUN", {})

    task_node = _find_task_node(db, dataset_id, task)
    if task_node:
        db.create_relationship(task_node, run_node, "HAS_GLM_RUN", {})

    # Summary (Yeo17)
    yeo17 = data.get("yeo17") or {}
    if yeo17:
        summary_id = f"glmrun_summary:{run_id}"
        summary_props = {
            "id": summary_id,
            "summary_path": yeo17.get("summary_path"),
            "edges_path": yeo17.get("edges_path"),
            "edges_cypher": yeo17.get("edges_cypher"),
            "robustness_json": yeo17.get("robustness_json"),
            "robustness_md": yeo17.get("robustness_md"),
            "status": yeo17.get("status"),
        }
        summary_node = db.create_node("ResultSummary", summary_props, node_id=summary_id)
        db.create_relationship(run_node, summary_node, "HAS_SUMMARY", {})

    # Variants + artifacts
    for variant in data.get("variants", []):
        model_id = variant.get("model_id")
        variant_node_id = f"glmvariant:{run_id}:{model_id}"
        props = {
            "id": variant_node_id,
            "model_id": model_id,
            "variant_id": variant.get("variant_id"),
            "selection_reason": variant.get("selection_reason"),
            "decision_points": variant.get("decision_points"),
            "spec_path": variant.get("spec_path"),
            "spec_sha256": variant.get("spec_sha256"),
            "output_dir": variant.get("output_dir"),
            "status": variant.get("status"),
            "exit_code": variant.get("exit_code"),
            "rationale": variant.get("rationale"),
            "contrast": variant.get("contrast"),
            "fitlins_params": variant.get("fitlins_params"),
            "references": variant.get("references"),
            "literature_evidence": variant.get("literature_evidence"),
            "model_x": variant.get("model_x"),
        }
        variant_node = db.create_node("GLMVariant", props, node_id=variant_node_id)
        db.create_relationship(run_node, variant_node, "HAS_VARIANT", {})

        for art in variant.get("artifacts", []) or []:
            path_val = art.get("path")
            if not path_val:
                continue
            artifact_id = _artifact_id(path_val)
            artifact_props = {
                "id": artifact_id,
                "path": path_val,
                "kind": art.get("kind"),
            }
            artifact_node = db.create_node("Artifact", artifact_props, node_id=artifact_id)
            db.create_relationship(variant_node, artifact_node, "PRODUCES", {})

    return {"run_id": run_id, "dataset_id": dataset_id, "task": task}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to run_manifest.json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.exists():
        logger.error("Manifest not found: %s", manifest_path)
        return 2
    result = _ingest_manifest(manifest_path)
    logger.info("Ingested GLMRun %s (%s/%s)", result["run_id"], result["dataset_id"], result["task"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
