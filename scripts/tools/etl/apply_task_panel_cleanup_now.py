#!/usr/bin/env python3
"""Apply targeted cleanup for task-panel rows explicitly marked cleanup_now."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable, Sequence
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup-rows", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--neo4j-uri", default=_env("NEO4J_URI", "bolt://localhost:7687")
    )
    parser.add_argument("--neo4j-user", default=_env("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=_env("NEO4J_PASSWORD"))
    parser.add_argument("--neo4j-database", default=_env("NEO4J_DATABASE"))
    return parser.parse_args(argv)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def _fetch_state(
    tx: Any, *, claim_id: str, paper_id: str, run_id: str, old_task_id: str
) -> dict[str, Any] | None:
    row = tx.run(
        """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (p_claim:Publication {id: c.paper_id})
        OPTIONAL MATCH (p_input:Publication {id: $paper_id})
        WITH c, coalesce(p_claim, p_input) AS p
        OPTIONAL MATCH (p)-[m:MENTIONS]->(:Task {id: $old_task_id})
        WHERE m.run_id = $run_id
        OPTIONAL MATCH (ev:EvidenceSpan)-[:SUPPORTS]->(c)
        RETURN
          c.id AS claim_id,
          c.target_id AS current_target_id,
          p.id AS publication_id,
          count(DISTINCT m) AS mention_count,
          collect(DISTINCT ev.id) AS evidence_ids
        """,
        {
            "claim_id": claim_id,
            "paper_id": paper_id,
            "run_id": run_id,
            "old_task_id": old_task_id,
        },
    ).single()
    if row is None or row.get("claim_id") is None:
        return None
    evidence_ids = [
        str(item).strip()
        for item in (row.get("evidence_ids") or [])
        if str(item or "").strip()
    ]
    return {
        "claim_id": str(row.get("claim_id") or "").strip(),
        "current_target_id": str(row.get("current_target_id") or "").strip(),
        "publication_id": str(row.get("publication_id") or "").strip(),
        "mention_count": int(row.get("mention_count") or 0),
        "evidence_ids": evidence_ids,
    }


def _apply_cleanup(
    tx: Any, *, claim_id: str, publication_id: str, run_id: str, old_task_id: str, evidence_ids: list[str]
) -> dict[str, Any]:
    mention_row = tx.run(
        """
        MATCH (p:Publication {id: $publication_id})-[m:MENTIONS]->(:Task {id: $old_task_id})
        WHERE m.run_id = $run_id
        DELETE m
        RETURN count(*) AS deleted_mentions
        """,
        {
            "publication_id": publication_id,
            "old_task_id": old_task_id,
            "run_id": run_id,
        },
    ).single()
    claim_row = tx.run(
        """
        MATCH (c:Claim {id: $claim_id})
        DETACH DELETE c
        RETURN count(*) AS deleted_claims
        """,
        {"claim_id": claim_id},
    ).single()
    evidence_row = tx.run(
        """
        UNWIND $evidence_ids AS evidence_id
        MATCH (ev:EvidenceSpan {id: evidence_id})
        WHERE NOT (ev)--()
        DELETE ev
        RETURN count(*) AS deleted_evidence
        """,
        {"evidence_ids": evidence_ids},
    ).single()
    return {
        "deleted_mentions": int((mention_row or {}).get("deleted_mentions") or 0),
        "deleted_claims": int((claim_row or {}).get("deleted_claims") or 0),
        "deleted_evidence": int((evidence_row or {}).get("deleted_evidence") or 0),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    cleanup_rows_path = args.cleanup_rows.expanduser().resolve()
    output_json = args.output_json.expanduser().resolve()
    rows = list(_iter_jsonl(cleanup_rows_path))
    results: list[dict[str, Any]] = []
    summary = {
        "candidate_rows": len(rows),
        "needs_cleanup": 0,
        "cleaned_rows": 0,
        "skipped_missing_claim": 0,
        "skipped_target_drift": 0,
        "claims_deleted": 0,
        "evidence_deleted": 0,
        "mention_edges_deleted": 0,
    }

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            for row in rows:
                claim_id = str(row.get("claim_id") or "").strip()
                paper_id = str(row.get("paper_id") or "").strip()
                run_id = str(row.get("run_id") or "").strip()
                old_task_id = str(row.get("old_task_id") or "").strip()
                state = session.execute_read(
                    _fetch_state,
                    claim_id=claim_id,
                    paper_id=paper_id,
                    run_id=run_id,
                    old_task_id=old_task_id,
                )
                if state is None:
                    summary["skipped_missing_claim"] += 1
                    results.append(
                        {
                            "status": "skipped_missing_claim",
                            "claim_id": claim_id,
                            "paper_id": paper_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                        }
                    )
                    continue
                current_target_id = str(state.get("current_target_id") or "").strip()
                if current_target_id != old_task_id:
                    summary["skipped_target_drift"] += 1
                    results.append(
                        {
                            "status": "skipped_target_drift",
                            "claim_id": claim_id,
                            "paper_id": paper_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                            "current_target_id": current_target_id,
                        }
                    )
                    continue

                if args.dry_run:
                    summary["needs_cleanup"] += 1
                    results.append(
                        {
                            "status": "needs_cleanup",
                            "claim_id": claim_id,
                            "paper_id": paper_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                            "publication_id": state.get("publication_id"),
                            "mention_count": state.get("mention_count"),
                            "evidence_ids": state.get("evidence_ids"),
                        }
                    )
                    continue

                apply_result = session.execute_write(
                    _apply_cleanup,
                    claim_id=claim_id,
                    publication_id=str(state.get("publication_id") or paper_id),
                    run_id=run_id,
                    old_task_id=old_task_id,
                    evidence_ids=list(state.get("evidence_ids") or []),
                )
                summary["cleaned_rows"] += 1
                summary["claims_deleted"] += int(apply_result["deleted_claims"])
                summary["evidence_deleted"] += int(apply_result["deleted_evidence"])
                summary["mention_edges_deleted"] += int(apply_result["deleted_mentions"])
                results.append(
                    {
                        "status": "cleaned",
                        "claim_id": claim_id,
                        "paper_id": paper_id,
                        "run_id": run_id,
                        "old_task_id": old_task_id,
                        **apply_result,
                    }
                )

    report = {
        "generated_at": _utc_now_iso(),
        "dry_run": bool(args.dry_run),
        "cleanup_rows_path": str(cleanup_rows_path),
        "summary": summary,
        "results_sample": results[:50],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=True))
    print(f"Wrote report: {output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
