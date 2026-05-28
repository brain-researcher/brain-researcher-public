#!/usr/bin/env python3
"""Rewire task-panel claim targets to exact target ids for exact reroute batches.

This migrates previously ingested task-panel records whose canonical targets
are exact namespaces such as ``task:subfamily:*``, ``task:family:*``, or
selected ``concept:*`` ids. It updates ``Claim.target_id``, preserves
``Publication-[:MENTIONS]`` edge properties for the corresponding
``MeasurementRun.run_id``, and prunes orphaned legacy ``task:onvoc:*`` nodes
that become isolated after rewiring.

Operational rule:

- task exact reroutes usually follow ``kg_task_panel`` ingest
- concept exact reroutes should use this migration path directly and pass
  ``--exact-prefix concept:``
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.neurokg.etl.loaders.gabriel_measurements import (
    DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    compute_gabriel_variables,
)

DEFAULT_EXACT_PREFIXES = ("task:subfamily:", "task:family:")
TOOL_TO_METHOD = {
    "codify": "llm_codify",
    "extract": "llm_extract",
    "merge": "llm_merge",
    "deduplicate": "llm_deduplicate",
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--records-path",
        type=Path,
        default=None,
        help="Optional explicit task_panel_records.jsonl path. Defaults to sibling of manifest.",
    )
    parser.add_argument(
        "--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687")
    )
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    parser.add_argument(
        "--exact-prefix",
        action="append",
        dest="exact_prefixes",
        default=[],
        help=(
            "Exact target-id prefixes to migrate. Can be repeated. "
            "Defaults to task-only prefixes; pass --exact-prefix concept: "
            "for Concept reroute batches."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "tmp/task_panel_exact_id_migration/task_panel_exact_id_migration_report.json"
        ),
    )
    return parser.parse_args(argv)


def _records_path_from_args(args: argparse.Namespace) -> Path:
    if args.records_path is not None:
        return args.records_path
    return args.manifest.resolve().parent / "task_panel_records.jsonl"


def _target_node_props(record: dict[str, Any], *, target_type: str) -> dict[str, Any]:
    target = dict(record.get("target") or {})
    mapping = dict(record.get("mapping") or {})
    task_panel = dict((record.get("normalization") or {}).get("task_panel") or {})
    if target_type == "Task":
        props = {
            "name": target.get("label") or target.get("name"),
            "source": "gabriel",
            "onvoc_id": target.get("onvoc_id") or mapping.get("onvoc_id"),
            "onvoc_uri": target.get("onvoc_uri") or mapping.get("onvoc_uri"),
            "task_fold_mode": task_panel.get("task_fold_mode") or "subfamily",
            "family_id": task_panel.get("family_id"),
            "subfamily_id": task_panel.get("subfamily_id"),
            "original_id": target.get("original_id") or task_panel.get("base_task_id"),
        }
    else:
        props = {
            "label": target.get("label") or target.get("name"),
            "name": target.get("label") or target.get("name"),
            "source": "gabriel",
            "original_id": target.get("original_id") or mapping.get("original_canonical_id"),
        }
    return {key: value for key, value in props.items() if value is not None}


def _normalize_claim_kind(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {
        "replication",
        "direct_replication",
        "conceptual_replication",
    }:
        return "replication"
    if normalized in {
        "failed_replication",
        "replication_failure",
        "failed_direct_replication",
    }:
        return "failed_replication"
    if normalized in {"null_result", "null", "negative_result"}:
        return "null_result"
    if normalized in {"contradiction", "contradicts", "conflict"}:
        return "contradiction"
    return "claim"


def _relationship_props_from_record(record: dict[str, Any]) -> dict[str, Any]:
    run = dict(record.get("run") or {})
    claim = dict(record.get("claim") or {})
    variables = compute_gabriel_variables(
        record,
        required_provenance_fields=DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    )
    tool = str(run.get("tool") or record.get("tool") or "extract").lower()
    method = TOOL_TO_METHOD.get(tool, "llm_extract")
    now = datetime.now(timezone.utc).isoformat()
    props = {
        "source": "gabriel",
        "method": method,
        "confidence": variables.mapping_confidence,
        "mention_strength": variables.mention_strength,
        "mapping_confidence": variables.mapping_confidence,
        "claim_kind": _normalize_claim_kind(
            claim.get("kind") or claim.get("claim_kind") or record.get("claim_kind")
        ),
        "claim_polarity": variables.claim_polarity,
        "claim_strength": variables.claim_strength,
        "evidence_quality": variables.evidence_quality,
        "evidence_quality_score": variables.evidence_quality_score,
        "method_rigor": variables.method_rigor,
        "provenance_completeness": variables.provenance_completeness,
        "run_id": str(run.get("run_id") or record.get("run_id") or "unknown"),
        "prompt_hash": str(
            run.get("prompt_hash") or record.get("prompt_hash") or "unknown"
        ),
        "template_hash": str(
            run.get("template_hash") or record.get("template_hash") or "unknown"
        ),
        "raw_response_path": str(
            run.get("raw_response_path") or record.get("raw_response_path") or "unknown"
        ),
        "model": str(run.get("model") or record.get("model") or "unknown"),
        "loader_version": "gabriel-loader/v1",
        "timestamp": str(record.get("timestamp") or now),
    }
    return {key: value for key, value in props.items() if value is not None}


def _load_rows(
    records_path: Path, exact_prefixes: Sequence[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(
        records_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        target = dict(payload.get("target") or {})
        target_id = str(target.get("id") or "").strip()
        if not target_id.startswith(tuple(exact_prefixes)):
            continue
        raw_target_type = str(target.get("type") or payload.get("target_type") or "Task")
        target_type = "Task" if raw_target_type.strip().lower() in {"task", "taskparadigm", "paradigm"} else "Concept"
        paper = dict(payload.get("paper") or {})
        run = dict(payload.get("run") or {})
        claim = dict(payload.get("claim") or {})
        paper_id = str(paper.get("id") or "").strip()
        run_id = str(run.get("run_id") or "").strip()
        claim_id = str(claim.get("id") or "").strip()
        if not paper_id or not run_id or not claim_id:
            continue
        rows.append(
            {
                "line_no": line_no,
                "paper_id": paper_id,
                "run_id": run_id,
                "claim_id": claim_id,
                "new_target_id": target_id,
                "new_target_type": target_type,
                "target_props": _target_node_props(payload, target_type=target_type),
                "record": payload,
            }
        )
    return rows


def _fetch_state(
    tx: Any, *, paper_id: str, run_id: str, claim_id: str, new_target_id: str
) -> dict[str, Any] | None:
    row = tx.run(
        """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (p_claim:Publication {id: c.paper_id})
        OPTIONAL MATCH (p_input:Publication {id: $paper_id})
        WITH c, coalesce(p_claim, p_input) AS p
        OPTIONAL MATCH (p)-[m:MENTIONS]->(t)
        WHERE m.run_id = $run_id
        RETURN
          c.target_id AS claim_target_id,
          c.paper_id AS claim_paper_id,
          p.id AS publication_id,
          EXISTS {
            MATCH (p)-[:MENTIONS]->({id: $new_target_id})
          } AS has_new_target_link,
          collect({
            target_id: t.id,
            target_labels: labels(t),
            target_name: coalesce(t.name, t.label),
            rel_props: properties(m)
          }) AS run_mentions
        """,
        {
            "paper_id": paper_id,
            "run_id": run_id,
            "claim_id": claim_id,
            "new_target_id": new_target_id,
        },
    ).single()
    if row is None:
        return None
    run_mentions = [
        dict(item)
        for item in (row.get("run_mentions") or [])
        if item.get("target_id") is not None
    ]
    return {
        "claim_target_id": row.get("claim_target_id"),
        "claim_paper_id": row.get("claim_paper_id"),
        "publication_id": row.get("publication_id"),
        "has_new_target_link": bool(row.get("has_new_target_link")),
        "run_mentions": run_mentions,
    }


def _apply_row(
    tx: Any, *, row: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    paper_id = row["paper_id"]
    run_id = row["run_id"]
    claim_id = row["claim_id"]
    new_target_id = row["new_target_id"]
    new_target_type = row["new_target_type"]
    target_props = dict(row["target_props"])
    publication_id = str(
        state.get("publication_id") or state.get("claim_paper_id") or row["paper_id"]
    ).strip()

    claim_target_id = str(state.get("claim_target_id") or "").strip()
    has_new_target_link = bool(state.get("has_new_target_link"))
    run_mentions = list(state.get("run_mentions") or [])
    new_run_mentions = [
        item for item in run_mentions if item.get("target_id") == new_target_id
    ]
    old_mentions = [item for item in run_mentions if item.get("target_id") != new_target_id]

    if claim_target_id == new_target_id and has_new_target_link and not old_mentions:
        return {
            "status": "unchanged",
            "claim_id": claim_id,
            "paper_id": paper_id,
            "run_id": run_id,
            "new_target_id": new_target_id,
        }

    source_props: dict[str, Any] = {}
    if new_run_mentions:
        source_props = dict(new_run_mentions[0].get("rel_props") or {})
    elif claim_target_id:
        for item in old_mentions:
            if item.get("target_id") == claim_target_id:
                source_props = dict(item.get("rel_props") or {})
                break
    if not source_props and old_mentions:
        source_props = dict(old_mentions[0].get("rel_props") or {})
    if not source_props:
        source_props = _relationship_props_from_record(dict(row.get("record") or {}))

    if not source_props:
        return {
            "status": "skipped_missing_mentions",
            "claim_id": claim_id,
            "paper_id": paper_id,
            "run_id": run_id,
            "new_target_id": new_target_id,
        }

    if new_target_type == "Task":
        tx.run(
            """
            MATCH (c:Claim {id: $claim_id})
            MATCH (p:Publication {id: $publication_id})
            MERGE (t:Task {id: $new_target_id})
            SET t += $target_props
            MERGE (p)-[m:MENTIONS]->(t)
            SET m += $rel_props
            SET c.target_id = $new_target_id
            """,
            {
                "claim_id": claim_id,
                "publication_id": publication_id,
                "new_target_id": new_target_id,
                "target_props": target_props,
                "rel_props": source_props,
            },
        )
    else:
        tx.run(
            """
            MATCH (c:Claim {id: $claim_id})
            MATCH (p:Publication {id: $publication_id})
            MERGE (t:Concept {id: $new_target_id})
            SET t += $target_props
            MERGE (p)-[m:MENTIONS]->(t)
            SET m += $rel_props
            SET c.target_id = $new_target_id
            """,
            {
                "claim_id": claim_id,
                "publication_id": publication_id,
                "new_target_id": new_target_id,
                "target_props": target_props,
                "rel_props": source_props,
            },
        )

    deleted_edges = 0
    pruned_nodes = 0
    for item in old_mentions:
        old_target_id = str(item.get("target_id") or "").strip()
        if not old_target_id or old_target_id == new_target_id:
            continue
        row_delete = tx.run(
            """
            MATCH (p:Publication {id: $publication_id})-[m:MENTIONS]->(oldt {id: $old_target_id})
            WHERE m.run_id = $run_id
            DELETE m
            RETURN count(*) AS deleted_edges
            """,
            {
                "publication_id": publication_id,
                "old_target_id": old_target_id,
                "run_id": run_id,
            },
        ).single()
        deleted_edges += int((row_delete or {}).get("deleted_edges") or 0)

        if old_target_id.startswith("task:onvoc:"):
            row_prune = tx.run(
                """
                MATCH (oldt:Task {id: $old_target_id})
                WHERE NOT (oldt)--()
                DELETE oldt
                RETURN count(*) AS deleted_nodes
                """,
                {"old_target_id": old_target_id},
            ).single()
            pruned_nodes += int((row_prune or {}).get("deleted_nodes") or 0)

    return {
        "status": "migrated",
        "claim_id": claim_id,
        "paper_id": paper_id,
        "run_id": run_id,
        "new_target_id": new_target_id,
        "old_mentions_deleted": deleted_edges,
        "orphan_nodes_pruned": pruned_nodes,
    }


def build_report(
    *,
    args: argparse.Namespace,
    records_path: Path,
    candidate_rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "candidate_rows": len(candidate_rows),
        "migrated": 0,
        "unchanged": 0,
        "needs_migration": 0,
        "skipped_missing_state": 0,
        "skipped_missing_mentions": 0,
        "old_mentions_deleted": 0,
        "orphan_nodes_pruned": 0,
    }
    for result in results:
        status = str(result.get("status") or "")
        if status == "migrated":
            summary["migrated"] += 1
            summary["old_mentions_deleted"] += int(
                result.get("old_mentions_deleted") or 0
            )
            summary["orphan_nodes_pruned"] += int(
                result.get("orphan_nodes_pruned") or 0
            )
        elif status == "unchanged":
            summary["unchanged"] += 1
        elif status == "needs_migration":
            summary["needs_migration"] += 1
        elif status == "skipped_missing_state":
            summary["skipped_missing_state"] += 1
        elif status == "skipped_missing_mentions":
            summary["skipped_missing_mentions"] += 1

    return {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "manifest_path": str(args.manifest.resolve()),
        "records_path": str(records_path.resolve()),
        "exact_prefixes": list(args.exact_prefixes or DEFAULT_EXACT_PREFIXES),
        "summary": summary,
        "results_sample": results[:50],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    records_path = _records_path_from_args(args)
    if not records_path.exists():
        raise SystemExit(f"Missing task-panel records file: {records_path}")

    exact_prefixes = tuple(args.exact_prefixes or DEFAULT_EXACT_PREFIXES)
    rows = _load_rows(records_path, exact_prefixes)
    results: list[dict[str, Any]] = []

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            for row in rows:
                state = session.execute_read(
                    _fetch_state,
                    paper_id=row["paper_id"],
                    run_id=row["run_id"],
                    claim_id=row["claim_id"],
                    new_target_id=row["new_target_id"],
                )
                if state is None:
                    results.append(
                        {
                            "status": "skipped_missing_state",
                            "claim_id": row["claim_id"],
                            "paper_id": row["paper_id"],
                            "run_id": row["run_id"],
                            "new_target_id": row["new_target_id"],
                        }
                    )
                    continue

                claim_target_id = str(state.get("claim_target_id") or "").strip()
                has_new_target_link = bool(state.get("has_new_target_link"))
                run_mentions = list(state.get("run_mentions") or [])
                old_mentions = [
                    item
                    for item in run_mentions
                    if item.get("target_id") != row["new_target_id"]
                ]
                if (
                    claim_target_id == row["new_target_id"]
                    and has_new_target_link
                    and not old_mentions
                ):
                    results.append(
                        {
                            "status": "unchanged",
                            "claim_id": row["claim_id"],
                            "paper_id": row["paper_id"],
                            "run_id": row["run_id"],
                            "new_target_id": row["new_target_id"],
                        }
                    )
                    continue

                if args.dry_run:
                    results.append(
                        {
                            "status": "needs_migration",
                            "claim_id": row["claim_id"],
                            "paper_id": row["paper_id"],
                            "run_id": row["run_id"],
                            "new_target_id": row["new_target_id"],
                            "claim_target_id": claim_target_id,
                            "claim_paper_id": state.get("claim_paper_id"),
                            "publication_id": state.get("publication_id"),
                            "run_mention_target_ids": [
                                item.get("target_id")
                                for item in run_mentions
                                if item.get("target_id")
                            ],
                            "has_new_target_link": has_new_target_link,
                        }
                    )
                    continue

                results.append(session.execute_write(_apply_row, row=row, state=state))

    report = build_report(
        args=args,
        records_path=records_path,
        candidate_rows=rows,
        results=results,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=True))
    print(f"Wrote report: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
