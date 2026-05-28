#!/usr/bin/env python3
"""Rollback the accidental Psych-101 live-audit snapshot from Neo4j.

This script is intentionally narrow. It targets only the known
``dataset_id=psych101-live-audit`` residue plus an explicit allowlist of local
Psych-101 task/task-family nodes that were created during the bad audit pass.
It defaults to preview mode; pass ``--apply`` to execute deletions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

DEFAULT_DATASET_ID = "psych101-live-audit"
DEFAULT_TASK_IDS = [
    "psych101:task:default-mode-network-dmn-localizer",
    "psych101:task:exp",
    "psych101:task:exp1",
    "psych101:task:exp2",
    "psych101:task:exp3",
    "psych101:task:exp4",
    "psych101:task:finger-tapping-unimanual-bimanual",
    "psych101:task:stop-signal-task-cancel",
    "psych101:task:word-reading-vs-pseudoword-reading",
]
DEFAULT_FAMILY_IDS = [
    "psych101:family:attention",
    "psych101:family:decision-making",
    "psych101:family:learning",
    "psych101:family:memory",
    "psych101:family:social-cognition",
]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument(
        "--task-id",
        dest="task_ids",
        action="append",
        default=None,
        help="Explicit local Psych-101 task id to target. Repeatable.",
    )
    parser.add_argument(
        "--family-id",
        dest="family_ids",
        action="append",
        default=None,
        help="Explicit local Psych-101 task-family id to target. Repeatable.",
    )
    parser.add_argument(
        "--expected-datasets",
        type=int,
        default=1,
        help="Guardrail: expected dataset-node count before deletion.",
    )
    parser.add_argument(
        "--expected-experiments",
        type=int,
        default=76,
        help="Guardrail: expected experiment-node count before deletion.",
    )
    parser.add_argument(
        "--expected-tasks",
        type=int,
        default=len(DEFAULT_TASK_IDS),
        help="Guardrail: expected allowlist task-node count before deletion.",
    )
    parser.add_argument(
        "--expected-families",
        type=int,
        default=len(DEFAULT_FAMILY_IDS),
        help="Guardrail: expected allowlist family-node count before deletion.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply even if preview counts differ from the expected guardrail counts.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute deletions. Without this flag the script only previews.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON summary output path.",
    )
    parser.add_argument("--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    return parser.parse_args(argv)


def _normalize_targets(values: list[str] | None, defaults: list[str]) -> list[str]:
    items = values if values else defaults
    out: list[str] = []
    seen: set[str] = set()
    for value in items:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _single_int(tx: Any, query: str, params: dict[str, Any], key: str) -> int:
    row = tx.run(query, params).single()
    if row is None:
        return 0
    return int(row.get(key) or 0)


def _single_list(tx: Any, query: str, params: dict[str, Any], key: str) -> list[str]:
    row = tx.run(query, params).single()
    if row is None:
        return []
    values = row.get(key) or []
    return [str(value).strip() for value in values if str(value or "").strip()]


def _preview(tx: Any, *, dataset_id: str, task_ids: list[str], family_ids: list[str]) -> dict[str, Any]:
    params = {
        "dataset_id": dataset_id,
        "task_ids": task_ids,
        "family_ids": family_ids,
    }
    return {
        "dataset_nodes": _single_int(
            tx,
            """
            MATCH (d:Dataset:Psych101Dataset)
            WHERE d.id = $dataset_id OR d.dataset_id = $dataset_id
            RETURN count(d) AS count
            """,
            params,
            "count",
        ),
        "dataset_ids": _single_list(
            tx,
            """
            MATCH (d:Dataset:Psych101Dataset)
            WHERE d.id = $dataset_id OR d.dataset_id = $dataset_id
            RETURN collect(d.id) AS ids
            """,
            params,
            "ids",
        ),
        "experiment_nodes": _single_int(
            tx,
            """
            MATCH (e:Experiment:Psych101Experiment {dataset_id: $dataset_id})
            RETURN count(e) AS count
            """,
            params,
            "count",
        ),
        "experiment_ids_sample": _single_list(
            tx,
            """
            MATCH (e:Experiment:Psych101Experiment {dataset_id: $dataset_id})
            WITH e ORDER BY e.id
            RETURN collect(e.id)[0..25] AS ids
            """,
            params,
            "ids",
        ),
        "task_nodes": _single_int(
            tx,
            """
            MATCH (t:Task)
            WHERE t.id IN $task_ids
            RETURN count(t) AS count
            """,
            params,
            "count",
        ),
        "task_ids_present": _single_list(
            tx,
            """
            MATCH (t:Task)
            WHERE t.id IN $task_ids
            RETURN collect(t.id) AS ids
            """,
            params,
            "ids",
        ),
        "task_ids_detachable": _single_list(
            tx,
            """
            MATCH (t:Task)
            WHERE t.id IN $task_ids
              AND NOT EXISTS { MATCH (:Experiment)-[:USES_TASK]->(t) }
            RETURN collect(t.id) AS ids
            """,
            params,
            "ids",
        ),
        "family_nodes": _single_int(
            tx,
            """
            MATCH (f:TaskFamily)
            WHERE f.id IN $family_ids
            RETURN count(f) AS count
            """,
            params,
            "count",
        ),
        "family_ids_present": _single_list(
            tx,
            """
            MATCH (f:TaskFamily)
            WHERE f.id IN $family_ids
            RETURN collect(f.id) AS ids
            """,
            params,
            "ids",
        ),
        "family_ids_detachable": _single_list(
            tx,
            """
            MATCH (f:TaskFamily)
            WHERE f.id IN $family_ids
              AND NOT EXISTS { MATCH (:Experiment)-[:CLASSIFIED_UNDER]->(f) }
              AND NOT EXISTS { MATCH (:Task)-[:BELONGS_TO_FAMILY]->(f) }
            RETURN collect(f.id) AS ids
            """,
            params,
            "ids",
        ),
    }


def _delete_experiments(tx: Any, *, dataset_id: str) -> dict[str, Any]:
    row = tx.run(
        """
        MATCH (e:Experiment:Psych101Experiment {dataset_id: $dataset_id})
        WITH collect(e) AS nodes
        FOREACH (n IN nodes | DETACH DELETE n)
        RETURN size(nodes) AS deleted_experiments
        """,
        {"dataset_id": dataset_id},
    ).single()
    return {"deleted_experiments": int((row or {}).get("deleted_experiments") or 0)}


def _delete_dataset(tx: Any, *, dataset_id: str) -> dict[str, Any]:
    row = tx.run(
        """
        MATCH (d:Dataset:Psych101Dataset)
        WHERE d.id = $dataset_id OR d.dataset_id = $dataset_id
        WITH collect(d) AS nodes
        FOREACH (n IN nodes | DETACH DELETE n)
        RETURN size(nodes) AS deleted_datasets
        """,
        {"dataset_id": dataset_id},
    ).single()
    return {"deleted_datasets": int((row or {}).get("deleted_datasets") or 0)}


def _delete_detachable_tasks(tx: Any, *, task_ids: list[str]) -> dict[str, Any]:
    row = tx.run(
        """
        MATCH (t:Task)
        WHERE t.id IN $task_ids
          AND NOT EXISTS { MATCH (:Experiment)-[:USES_TASK]->(t) }
        WITH collect(t) AS nodes, collect(t.id) AS deleted_ids
        FOREACH (n IN nodes | DETACH DELETE n)
        RETURN size(nodes) AS deleted_orphan_tasks, deleted_ids
        """,
        {"task_ids": task_ids},
    ).single()
    return {
        "deleted_orphan_tasks": int((row or {}).get("deleted_orphan_tasks") or 0),
        "deleted_task_ids": [
            str(value).strip()
            for value in ((row or {}).get("deleted_ids") or [])
            if str(value or "").strip()
        ],
    }


def _delete_detachable_families(tx: Any, *, family_ids: list[str]) -> dict[str, Any]:
    row = tx.run(
        """
        MATCH (f:TaskFamily)
        WHERE f.id IN $family_ids
          AND NOT EXISTS { MATCH (:Experiment)-[:CLASSIFIED_UNDER]->(f) }
          AND NOT EXISTS { MATCH (:Task)-[:BELONGS_TO_FAMILY]->(f) }
        WITH collect(f) AS nodes, collect(f.id) AS deleted_ids
        FOREACH (n IN nodes | DETACH DELETE n)
        RETURN size(nodes) AS deleted_orphan_families, deleted_ids
        """,
        {"family_ids": family_ids},
    ).single()
    return {
        "deleted_orphan_families": int((row or {}).get("deleted_orphan_families") or 0),
        "deleted_family_ids": [
            str(value).strip()
            for value in ((row or {}).get("deleted_ids") or [])
            if str(value or "").strip()
        ],
    }


def _guardrail_ok(args: argparse.Namespace, preview: dict[str, Any]) -> bool:
    return (
        preview["dataset_nodes"] == args.expected_datasets
        and preview["experiment_nodes"] == args.expected_experiments
        and preview["task_nodes"] == args.expected_tasks
        and preview["family_nodes"] == args.expected_families
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    task_ids = _normalize_targets(args.task_ids, DEFAULT_TASK_IDS)
    family_ids = _normalize_targets(args.family_ids, DEFAULT_FAMILY_IDS)
    output_json = (
        args.output_json.expanduser().resolve()
        if args.output_json
        else (
            Path.cwd()
            / f"{args.dataset_id.replace('/', '_')}_rollback_summary.json"
        ).resolve()
    )

    payload: dict[str, Any] = {
        "dataset_id": args.dataset_id,
        "mode": "apply" if args.apply else "dry_run",
        "task_ids": task_ids,
        "family_ids": family_ids,
        "started_at": _utc_now_iso(),
    }

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            preview = session.execute_read(
                _preview,
                dataset_id=args.dataset_id,
                task_ids=task_ids,
                family_ids=family_ids,
            )
            payload["preview"] = preview
            payload["guardrail_ok"] = _guardrail_ok(args, preview)

            if args.apply and not payload["guardrail_ok"] and not args.force:
                payload["status"] = "guardrail_blocked"
                payload["message"] = (
                    "Preview counts differ from expected guardrails. "
                    "Re-run with --force only after inspecting the preview."
                )
            elif args.apply:
                delete_summary: dict[str, Any] = {}
                delete_summary.update(
                    session.execute_write(_delete_experiments, dataset_id=args.dataset_id)
                )
                delete_summary.update(
                    session.execute_write(_delete_dataset, dataset_id=args.dataset_id)
                )
                delete_summary.update(
                    session.execute_write(_delete_detachable_tasks, task_ids=task_ids)
                )
                delete_summary.update(
                    session.execute_write(_delete_detachable_families, family_ids=family_ids)
                )
                payload["delete_summary"] = delete_summary
                payload["status"] = "applied"
            else:
                payload["status"] = "preview_only"

            payload["final"] = session.execute_read(
                _preview,
                dataset_id=args.dataset_id,
                task_ids=task_ids,
                family_ids=family_ids,
            )

    payload["finished_at"] = _utc_now_iso()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    if payload["status"] == "guardrail_blocked":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
