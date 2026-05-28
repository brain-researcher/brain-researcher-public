#!/usr/bin/env python3
"""Promote salvage-v3 task panel targets for four audited KGGEN claim records.

This migration is intentionally narrow. It rewires only the audited claim set
from their current task targets to the intended `task:subfamily:*` targets,
copies the corresponding publication->task `MENTIONS` relationship properties
for the same measurement run, updates `Claim.target_id`, and optionally deletes
orphaned legacy `task:onvoc:*` task nodes created by the earlier coarse ingest.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SalvageRecord:
    claim_id: str
    paper_id: str
    source_label: str
    new_task_id: str
    new_task_label: str
    onvoc_id: str
    onvoc_uri: str
    family_id: str
    subfamily_id: str


DEFAULT_RECORDS = (
    SalvageRecord(
        claim_id="claim:ab73ba5122cd",
        paper_id="pmid:41433755",
        source_label="Inclusive Face-Name fMRI Task",
        new_task_id="task:subfamily:sf_associative_memory",
        new_task_label="Episodic Memory",
        onvoc_id="ONVOC_0000493",
        onvoc_uri="https://w3id.org/onvoc/ONVOC_0000493",
        family_id="tf_ltm_declarative",
        subfamily_id="sf_associative_memory",
    ),
    SalvageRecord(
        claim_id="claim:a23bb813047e",
        paper_id="pmid:41438391",
        source_label="word reading",
        new_task_id="task:subfamily:sf_lexical_access_orthography",
        new_task_label="Reading Comprehension",
        onvoc_id="ONVOC_0000478",
        onvoc_uri="https://w3id.org/onvoc/ONVOC_0000478",
        family_id="tf_language_semantic",
        subfamily_id="sf_lexical_access_orthography",
    ),
    SalvageRecord(
        claim_id="claim:83990bb847c5",
        paper_id="pmid:41438391",
        source_label="phonological localizers",
        new_task_id="task:subfamily:sf_phonology_morphology",
        new_task_label="Phonological Processing",
        onvoc_id="ONVOC_0000475",
        onvoc_uri="https://w3id.org/onvoc/ONVOC_0000475",
        family_id="tf_language_semantic",
        subfamily_id="sf_phonology_morphology",
    ),
    SalvageRecord(
        claim_id="claim:57b5c9b8f733",
        paper_id="pmid:41438391",
        source_label="semantic localizers",
        new_task_id="task:subfamily:sf_semantic_processing",
        new_task_label="Semantics",
        onvoc_id="ONVOC_0000477",
        onvoc_uri="https://w3id.org/onvoc/ONVOC_0000477",
        family_id="tf_language_semantic",
        subfamily_id="sf_semantic_processing",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("tmp/task_panel_salvage_v3/task_panel_salvage_v3_report.json"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keep-orphan-old-tasks",
        action="store_true",
        help="Do not delete orphaned old task:onvoc:* nodes after rewiring.",
    )
    return parser.parse_args()


def _record_payloads() -> list[dict[str, str]]:
    return [
        {
            "claim_id": record.claim_id,
            "paper_id": record.paper_id,
            "source_label": record.source_label,
            "new_task_id": record.new_task_id,
            "new_task_label": record.new_task_label,
            "onvoc_id": record.onvoc_id,
            "onvoc_uri": record.onvoc_uri,
            "family_id": record.family_id,
            "subfamily_id": record.subfamily_id,
        }
        for record in DEFAULT_RECORDS
    ]


def _preview(session: Any, records: list[dict[str, str]]) -> list[dict[str, Any]]:
    query = """
    UNWIND $records AS row
    MATCH (c:Claim {id: row.claim_id})
    OPTIONAL MATCH (run:MeasurementRun)-[:GENERATED]->(c)
    OPTIONAL MATCH (p:Publication {id: c.paper_id})
    OPTIONAL MATCH (p)-[old_rel:MENTIONS]->(old_task:Task {id: c.target_id})
      WHERE run IS NULL OR old_rel.run_id = run.run_id
    OPTIONAL MATCH (new_task:Task {id: row.new_task_id})
    RETURN row.claim_id AS claim_id,
           row.paper_id AS paper_id,
           c.target_id AS current_target_id,
           row.new_task_id AS new_task_id,
           coalesce(run.run_id, "") AS run_id,
           old_task.id AS old_task_id,
           old_task.name AS old_task_name,
           old_rel IS NOT NULL AS old_mentions_present,
           new_task.id IS NOT NULL AS new_task_exists
    ORDER BY claim_id
    """
    return session.run(query, {"records": records}).data()


def _migrate(
    session: Any,
    records: list[dict[str, str]],
    *,
    delete_orphan_old_tasks: bool,
) -> list[dict[str, Any]]:
    query = """
    UNWIND $records AS row
    MATCH (c:Claim {id: row.claim_id})
    MATCH (p:Publication {id: c.paper_id})
    OPTIONAL MATCH (run:MeasurementRun)-[:GENERATED]->(c)
    OPTIONAL MATCH (p)-[old_rel:MENTIONS]->(old_task:Task {id: c.target_id})
      WHERE run IS NULL OR old_rel.run_id = run.run_id
    MERGE (new_task:Task {id: row.new_task_id})
      ON CREATE SET
        new_task.name = row.new_task_label,
        new_task.label = row.new_task_label,
        new_task.source = "gabriel",
        new_task.onvoc_id = row.onvoc_id,
        new_task.onvoc_uri = row.onvoc_uri,
        new_task.task_fold_mode = "subfamily",
        new_task.family_id = row.family_id,
        new_task.subfamily_id = row.subfamily_id,
        new_task.salvage_source_label = row.source_label,
        new_task.salvage_version = "task_panel_salvage_v3"
      ON MATCH SET
        new_task.name = coalesce(new_task.name, row.new_task_label),
        new_task.label = coalesce(new_task.label, row.new_task_label),
        new_task.onvoc_id = coalesce(new_task.onvoc_id, row.onvoc_id),
        new_task.onvoc_uri = coalesce(new_task.onvoc_uri, row.onvoc_uri),
        new_task.family_id = coalesce(new_task.family_id, row.family_id),
        new_task.subfamily_id = coalesce(new_task.subfamily_id, row.subfamily_id),
        new_task.task_fold_mode = coalesce(new_task.task_fold_mode, "subfamily"),
        new_task.salvage_version = "task_panel_salvage_v3"
    WITH row, c, p, run, old_rel, old_task, new_task
    OPTIONAL MATCH (p)-[existing_rel:MENTIONS]->(new_task)
      WHERE run IS NULL OR existing_rel.run_id = run.run_id
    FOREACH (_ IN CASE WHEN old_rel IS NOT NULL AND existing_rel IS NULL THEN [1] ELSE [] END |
      CREATE (p)-[new_rel:MENTIONS]->(new_task)
      SET new_rel = properties(old_rel)
    )
    SET c.target_id = row.new_task_id
    WITH row, c, old_task, old_rel, new_task, existing_rel
    FOREACH (_ IN CASE WHEN old_rel IS NOT NULL AND old_task IS NOT NULL AND old_task.id <> row.new_task_id THEN [1] ELSE [] END |
      DELETE old_rel
    )
    WITH row, c, old_task, new_task
    OPTIONAL MATCH (old_task)-[remaining]-()
    WITH row, c, old_task, new_task, count(remaining) AS remaining_rel_count
    FOREACH (_ IN CASE
      WHEN $delete_orphan_old_tasks
       AND old_task IS NOT NULL
       AND old_task.id STARTS WITH "task:onvoc:"
       AND remaining_rel_count = 0
      THEN [1] ELSE [] END |
      DELETE old_task
    )
    RETURN row.claim_id AS claim_id,
           row.paper_id AS paper_id,
           row.new_task_id AS new_task_id,
           new_task.name AS new_task_name,
           old_task.id AS old_task_id,
           remaining_rel_count AS old_task_remaining_relationships,
           c.target_id AS claim_target_id
    ORDER BY claim_id
    """
    return session.run(
        query,
        {
            "records": records,
            "delete_orphan_old_tasks": delete_orphan_old_tasks,
        },
    ).data()


def main() -> None:
    args = parse_args()
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    records = _record_payloads()
    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "records": records,
        "preview": [],
        "migration": [],
    }

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            report["preview"] = _preview(session, records)
            if not args.dry_run:
                report["migration"] = _migrate(
                    session,
                    records,
                    delete_orphan_old_tasks=not args.keep_orphan_old_tasks,
                )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    if args.dry_run:
        print(f"Dry-run complete for {len(records)} salvage-v3 records.")
    else:
        print(f"Migration complete for {len(records)} salvage-v3 records.")
    print(f"Wrote report: {args.output_json}")


if __name__ == "__main__":
    main()
