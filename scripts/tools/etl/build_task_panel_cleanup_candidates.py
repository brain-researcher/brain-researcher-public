#!/usr/bin/env python3
"""Build safe task-panel cleanup candidates with protection-list support."""

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
    parser.add_argument("--dropped-records", type=Path, required=True)
    parser.add_argument(
        "--protected-claim-ids",
        type=Path,
        action="append",
        default=[],
        help="Optional newline-delimited Claim.id list to exclude before cleanup selection. Can be repeated.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
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


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_protected_claim_ids(paths: Sequence[Path] | None) -> tuple[list[str], set[str]]:
    if not paths:
        return [], set()
    resolved_paths: list[str] = []
    protected_claim_ids: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Missing protected-claim-ids file: {resolved}")
        resolved_paths.append(str(resolved))
        protected_claim_ids.update(
            {
                line.strip()
                for line in resolved.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        )
    return resolved_paths, protected_claim_ids


def _fetch_cleanup_state(
    tx: Any,
    *,
    claim_id: str,
    paper_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    row = tx.run(
        """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (p_claim:Publication {id: c.paper_id})
        OPTIONAL MATCH (p_input:Publication {id: $paper_id})
        WITH c, coalesce(p_claim, p_input) AS p
        OPTIONAL MATCH (p)-[m:MENTIONS]->(t:Task)
        WHERE m.run_id = $run_id
        RETURN
          c.id AS claim_id,
          c.target_id AS current_target_id,
          c.paper_id AS claim_paper_id,
          p.id AS publication_id,
          collect(DISTINCT t.id) AS run_mention_task_ids
        """,
        {"claim_id": claim_id, "paper_id": paper_id, "run_id": run_id},
    ).single()
    if row is None or row.get("claim_id") is None:
        return None
    mention_task_ids = [
        str(item).strip()
        for item in (row.get("run_mention_task_ids") or [])
        if str(item or "").strip()
    ]
    return {
        "claim_id": str(row.get("claim_id") or "").strip(),
        "current_target_id": str(row.get("current_target_id") or "").strip(),
        "claim_paper_id": str(row.get("claim_paper_id") or "").strip(),
        "publication_id": str(row.get("publication_id") or "").strip(),
        "run_mention_task_ids": mention_task_ids,
        "missing_mentions": len(mention_task_ids) == 0,
        "missing_publication": not str(row.get("publication_id") or "").strip(),
    }


def _cleanup_row_from_record(row: dict[str, Any], live_state: dict[str, Any]) -> dict[str, Any]:
    paper = dict(row.get("paper") or {})
    target = dict(row.get("target") or {})
    mapping = dict(row.get("mapping") or {})
    claim = dict(row.get("claim") or {})
    run = dict(row.get("run") or {})
    return {
        "paper_id": str(paper.get("id") or "").strip(),
        "paper_title": str(paper.get("title") or "").strip(),
        "claim_id": str(claim.get("id") or "").strip(),
        "run_id": str(run.get("run_id") or "").strip(),
        "old_task_id": str(target.get("id") or "").strip(),
        "current_target_id": str(live_state.get("current_target_id") or "").strip(),
        "publication_id_live": str(live_state.get("publication_id") or "").strip(),
        "claim_paper_id_live": str(live_state.get("claim_paper_id") or "").strip(),
        "run_mention_task_ids": list(live_state.get("run_mention_task_ids") or []),
        "mapping_original": str(mapping.get("original_canonical_id") or "").strip(),
        "onvoc_id": str(
            target.get("onvoc_id") or mapping.get("onvoc_id") or ""
        ).strip(),
        "onvoc_label": str(target.get("label") or "").strip(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    dropped_records = args.dropped_records.expanduser().resolve()
    if not dropped_records.exists():
        raise SystemExit(f"Missing dropped-records file: {dropped_records}")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    protected_claim_ids_paths, protected_claim_ids = _load_protected_claim_ids(
        args.protected_claim_ids
    )
    rows = list(_iter_jsonl(dropped_records))

    cleanup_candidates: list[dict[str, Any]] = []
    skipped_protected: list[dict[str, Any]] = []
    skipped_target_drift: list[dict[str, Any]] = []
    skipped_missing_claim: list[dict[str, Any]] = []

    missing_mentions = 0
    missing_publication = 0

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            for row in rows:
                claim_id = str((row.get("claim") or {}).get("id") or "").strip()
                paper_id = str((row.get("paper") or {}).get("id") or "").strip()
                run_id = str((row.get("run") or {}).get("run_id") or "").strip()
                old_task_id = str((row.get("target") or {}).get("id") or "").strip()

                if claim_id in protected_claim_ids:
                    skipped_protected.append(
                        {
                            "claim_id": claim_id,
                            "paper_id": paper_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                        }
                    )
                    continue

                live_state = session.execute_read(
                    _fetch_cleanup_state,
                    claim_id=claim_id,
                    paper_id=paper_id,
                    run_id=run_id,
                )
                if live_state is None:
                    skipped_missing_claim.append(
                        {
                            "claim_id": claim_id,
                            "paper_id": paper_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                        }
                    )
                    continue

                if live_state.get("missing_mentions"):
                    missing_mentions += 1
                if live_state.get("missing_publication"):
                    missing_publication += 1

                current_target_id = str(live_state.get("current_target_id") or "").strip()
                if current_target_id != old_task_id:
                    skipped_target_drift.append(
                        {
                            "claim_id": claim_id,
                            "paper_id": paper_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                            "current_target_id": current_target_id,
                        }
                    )
                    continue

                cleanup_candidates.append(_cleanup_row_from_record(row, live_state))

    summary = {
        "generated_at": _utc_now_iso(),
        "dropped_records_path": str(dropped_records),
        "protected_claim_ids_paths": protected_claim_ids_paths,
        "counts": {
            "candidate_rows": len(rows),
            "cleanup_candidates": len(cleanup_candidates),
            "needs_cleanup": len(cleanup_candidates),
            "skipped_protected": len(skipped_protected),
            "skipped_target_drift": len(skipped_target_drift),
            "skipped_missing_claim": len(skipped_missing_claim),
            "missing_publication": missing_publication,
            "missing_mentions": missing_mentions,
            "protected_claim_ids_loaded": len(protected_claim_ids),
        },
        "artifacts": {
            "cleanup_candidates_jsonl": str(output_dir / "cleanup_candidates.jsonl"),
            "skipped_protected_jsonl": str(output_dir / "skipped_protected.jsonl"),
            "skipped_target_drift_jsonl": str(output_dir / "skipped_target_drift.jsonl"),
            "skipped_missing_claim_jsonl": str(output_dir / "skipped_missing_claim.jsonl"),
            "summary_json": str(output_dir / "cleanup_candidate_summary.json"),
        },
        "samples": {
            "cleanup_candidates": cleanup_candidates[:20],
            "skipped_protected": skipped_protected[:20],
            "skipped_target_drift": skipped_target_drift[:20],
            "skipped_missing_claim": skipped_missing_claim[:20],
        },
    }

    _write_jsonl(output_dir / "cleanup_candidates.jsonl", cleanup_candidates)
    _write_jsonl(output_dir / "skipped_protected.jsonl", skipped_protected)
    _write_jsonl(output_dir / "skipped_target_drift.jsonl", skipped_target_drift)
    _write_jsonl(output_dir / "skipped_missing_claim.jsonl", skipped_missing_claim)
    (output_dir / "cleanup_candidate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
