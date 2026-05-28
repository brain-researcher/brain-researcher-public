#!/usr/bin/env python3
"""Build a bounded drift-review pack for dropped task-panel rows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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
        "--cleanup-report",
        type=Path,
        required=True,
        help="Cleanup dry-run or apply report used for lineage/summary references.",
    )
    parser.add_argument(
        "--current-package-records",
        type=Path,
        default=None,
        help="Optional task_panel_records.jsonl from the current package for v8 router metadata.",
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


def _record_key(row: dict[str, Any]) -> str:
    paper_id = str((row.get("paper") or {}).get("id") or "").strip()
    claim_id = str((row.get("claim") or {}).get("id") or "").strip()
    run_id = str((row.get("run") or {}).get("run_id") or "").strip()
    return "::".join([paper_id, claim_id, run_id])


def _namespace_for_target(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "missing"
    if ":" not in text:
        return "other"
    if text.startswith("neurostore_task:"):
        return "neurostore_task"
    if text.startswith("task:onvoc:"):
        return "task:onvoc"
    if text.startswith("task:subfamily:"):
        return "task:subfamily"
    if text.startswith("task:family:"):
        return "task:family"
    return text.split(":", 1)[0]


def _review_bucket(namespace: str) -> str:
    if namespace == "neurostore_task":
        return "1_neurostore_task"
    if namespace == "task:onvoc":
        return "2_task_onvoc"
    if namespace in {"task:subfamily", "task:family"}:
        return "3_task_family"
    return "4_other"


def _semantic_cluster(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _build_current_package_index(
    records_path: Path | None,
) -> dict[str, dict[str, Any]]:
    if records_path is None:
        return {}
    resolved = records_path.expanduser().resolve()
    if not resolved.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(resolved):
        task_panel = dict((row.get("normalization") or {}).get("task_panel") or {})
        index[_record_key(row)] = {
            "v8_router_reason": str(task_panel.get("router_reason") or "").strip(),
            "v8_router_label_type": str(
                task_panel.get("router_label_type") or ""
            ).strip(),
            "v8_router_input_label": str(
                task_panel.get("router_input_label") or ""
            ).strip(),
            "v8_task_id": str(task_panel.get("task_id") or "").strip(),
        }
    return index


def _fetch_live_state(
    tx: Any,
    *,
    claim_id: str,
    paper_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    row = tx.run(
        """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (t:Task {id: c.target_id})
        OPTIONAL MATCH (p_claim:Publication {id: c.paper_id})
        OPTIONAL MATCH (p_input:Publication {id: $paper_id})
        WITH c, t, coalesce(p_claim, p_input) AS p
        OPTIONAL MATCH (p)-[m:MENTIONS]->(mt:Task)
        WHERE m.run_id = $run_id
        RETURN
          c.id AS claim_id,
          c.target_id AS current_target_id,
          c.paper_id AS claim_paper_id,
          p.id AS publication_id,
          coalesce(t.name, t.label, t.id) AS current_target_label,
          t.onvoc_id AS current_target_onvoc_id,
          t.family_id AS current_target_family_id,
          t.subfamily_id AS current_target_subfamily_id,
          collect(DISTINCT mt.id) AS run_mention_task_ids
        """,
        {"claim_id": claim_id, "paper_id": paper_id, "run_id": run_id},
    ).single()
    if row is None or row.get("claim_id") is None:
        return None
    return {
        "claim_id": str(row.get("claim_id") or "").strip(),
        "current_target_id": str(row.get("current_target_id") or "").strip(),
        "claim_paper_id": str(row.get("claim_paper_id") or "").strip(),
        "publication_id": str(row.get("publication_id") or "").strip(),
        "current_target_label": str(row.get("current_target_label") or "").strip(),
        "current_target_onvoc_id": str(
            row.get("current_target_onvoc_id") or ""
        ).strip(),
        "current_target_family_id": str(
            row.get("current_target_family_id") or ""
        ).strip(),
        "current_target_subfamily_id": str(
            row.get("current_target_subfamily_id") or ""
        ).strip(),
        "run_mention_task_ids": [
            str(item).strip()
            for item in (row.get("run_mention_task_ids") or [])
            if str(item or "").strip()
        ],
    }


def _build_review_row(
    row: dict[str, Any],
    *,
    live_state: dict[str, Any],
    current_package_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    paper = dict(row.get("paper") or {})
    target = dict(row.get("target") or {})
    mapping = dict(row.get("mapping") or {})
    onvoc = dict((row.get("normalization") or {}).get("onvoc") or {})
    task_panel = dict((row.get("normalization") or {}).get("task_panel") or {})
    claim = dict(row.get("claim") or {})
    run = dict(row.get("run") or {})

    old_task_id = str(target.get("id") or "").strip()
    current_target_id = str(live_state.get("current_target_id") or "").strip()
    current_namespace = _namespace_for_target(current_target_id)
    mapping_original = str(mapping.get("original_canonical_id") or "").strip()

    row_out = {
        "paper_id": str(paper.get("id") or "").strip(),
        "paper_title": str(paper.get("title") or "").strip(),
        "claim_id": str(claim.get("id") or "").strip(),
        "run_id": str(run.get("run_id") or "").strip(),
        "old_task_id": old_task_id,
        "old_task_namespace": _namespace_for_target(old_task_id),
        "current_target_id": current_target_id,
        "current_target_namespace": current_namespace,
        "current_target_label": str(live_state.get("current_target_label") or "").strip(),
        "review_bucket": _review_bucket(current_namespace),
        "mapping_original": mapping_original,
        "semantic_cluster": _semantic_cluster(mapping_original),
        "paper_original_id": str(paper.get("original_id") or "").strip(),
        "claim_paper_id_live": str(live_state.get("claim_paper_id") or "").strip(),
        "publication_id_live": str(live_state.get("publication_id") or "").strip(),
        "run_mention_task_ids": list(live_state.get("run_mention_task_ids") or []),
        "old_router_reason": str(task_panel.get("router_reason") or "").strip(),
        "v8_router_reason": "",
        "v8_router_label_type": "",
        "v8_router_input_label": "",
        "v8_task_id": "",
        "onvoc_id": str(
            target.get("onvoc_id") or onvoc.get("onvoc_id") or mapping.get("onvoc_id") or ""
        ).strip(),
        "onvoc_label": str(
            onvoc.get("onvoc_label") or target.get("label") or ""
        ).strip(),
        "current_target_onvoc_id": str(
            live_state.get("current_target_onvoc_id") or ""
        ).strip(),
        "current_target_family_id": str(
            live_state.get("current_target_family_id") or ""
        ).strip(),
        "current_target_subfamily_id": str(
            live_state.get("current_target_subfamily_id") or ""
        ).strip(),
    }
    if current_package_meta:
        row_out["v8_router_reason"] = str(
            current_package_meta.get("v8_router_reason") or ""
        ).strip()
        row_out["v8_router_label_type"] = str(
            current_package_meta.get("v8_router_label_type") or ""
        ).strip()
        row_out["v8_router_input_label"] = str(
            current_package_meta.get("v8_router_input_label") or ""
        ).strip()
        row_out["v8_task_id"] = str(current_package_meta.get("v8_task_id") or "").strip()
    return row_out


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = [
        "review_bucket",
        "current_target_namespace",
        "paper_id",
        "claim_id",
        "run_id",
        "old_task_id",
        "current_target_id",
        "mapping_original",
        "semantic_cluster",
        "onvoc_id",
        "onvoc_label",
        "v8_router_reason",
        "paper_title",
    ]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write(
                "\t".join(
                    str(row.get(column, "")).replace("\t", " ").replace("\n", " ")
                    for column in columns
                )
                + "\n"
            )


def build_summary(
    *,
    args: argparse.Namespace,
    cleanup_report: dict[str, Any],
    dropped_rows_count: int,
    drift_rows: Sequence[dict[str, Any]],
    missing_claims: Sequence[dict[str, Any]],
    unchanged_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    namespace_counts = Counter(row["current_target_namespace"] for row in drift_rows)
    bucket_counts = Counter(row["review_bucket"] for row in drift_rows)
    mapping_original_counts = Counter(row["mapping_original"] for row in drift_rows)
    transition_counts = Counter(
        (row["old_task_id"], row["current_target_id"]) for row in drift_rows
    )

    return {
        "generated_at": _utc_now_iso(),
        "dropped_records_path": str(args.dropped_records.resolve()),
        "cleanup_report_path": str(args.cleanup_report.resolve()),
        "current_package_records_path": (
            str(args.current_package_records.resolve())
            if args.current_package_records is not None
            else None
        ),
        "cleanup_report_summary": cleanup_report,
        "counts": {
            "candidate_rows": dropped_rows_count,
            "drift_rows": len(drift_rows),
            "missing_claim_rows": len(missing_claims),
            "unchanged_rows": len(unchanged_rows),
        },
        "counts_by_current_target_namespace": namespace_counts.most_common(),
        "counts_by_review_bucket": bucket_counts.most_common(),
        "counts_by_mapping_original": mapping_original_counts.most_common(50),
        "top_transitions": [
            [old_task_id, current_target_id, count]
            for (old_task_id, current_target_id), count in transition_counts.most_common(50)
        ],
        "artifacts": {
            "drift_review_pack_jsonl": str(args.output_dir / "drift_review_pack.jsonl"),
            "drift_review_pack_tsv": str(args.output_dir / "drift_review_pack.tsv"),
            "drift_review_summary_json": str(args.output_dir / "drift_review_summary.json"),
        },
        "samples": {
            "drift_rows": list(drift_rows[:20]),
            "missing_claim_rows": list(missing_claims[:20]),
            "unchanged_rows": list(unchanged_rows[:20]),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    dropped_records_path = args.dropped_records.expanduser().resolve()
    cleanup_report_path = args.cleanup_report.expanduser().resolve()
    if not dropped_records_path.exists():
        raise SystemExit(f"Missing dropped-records file: {dropped_records_path}")
    if not cleanup_report_path.exists():
        raise SystemExit(f"Missing cleanup report: {cleanup_report_path}")
    if not args.neo4j_password:
        raise SystemExit("Missing --neo4j-password (or NEO4J_PASSWORD env)")

    cleanup_report = json.loads(cleanup_report_path.read_text(encoding="utf-8"))
    current_package_index = _build_current_package_index(args.current_package_records)
    dropped_rows = list(_iter_jsonl(dropped_records_path))

    drift_rows: list[dict[str, Any]] = []
    missing_claim_rows: list[dict[str, Any]] = []
    unchanged_rows: list[dict[str, Any]] = []

    with GraphDatabase.driver(
        str(args.neo4j_uri),
        auth=(str(args.neo4j_user), str(args.neo4j_password)),
    ) as driver:
        with driver.session(database=args.neo4j_database or None) as session:
            for row in dropped_rows:
                paper_id = str((row.get("paper") or {}).get("id") or "").strip()
                claim_id = str((row.get("claim") or {}).get("id") or "").strip()
                run_id = str((row.get("run") or {}).get("run_id") or "").strip()
                live_state = session.execute_read(
                    _fetch_live_state,
                    claim_id=claim_id,
                    paper_id=paper_id,
                    run_id=run_id,
                )
                if live_state is None:
                    missing_claim_rows.append(
                        {
                            "paper_id": paper_id,
                            "claim_id": claim_id,
                            "run_id": run_id,
                            "old_task_id": str((row.get("target") or {}).get("id") or "").strip(),
                        }
                    )
                    continue

                old_task_id = str((row.get("target") or {}).get("id") or "").strip()
                current_target_id = str(live_state.get("current_target_id") or "").strip()
                if current_target_id == old_task_id:
                    unchanged_rows.append(
                        {
                            "paper_id": paper_id,
                            "claim_id": claim_id,
                            "run_id": run_id,
                            "old_task_id": old_task_id,
                            "current_target_id": current_target_id,
                        }
                    )
                    continue

                drift_rows.append(
                    _build_review_row(
                        row,
                        live_state=live_state,
                        current_package_meta=current_package_index.get(_record_key(row)),
                    )
                )

    drift_rows.sort(
        key=lambda row: (
            row["review_bucket"],
            row["current_target_namespace"],
            row["mapping_original"],
            row["paper_id"],
            row["claim_id"],
        )
    )

    summary = build_summary(
        args=args,
        cleanup_report=cleanup_report,
        dropped_rows_count=len(dropped_rows),
        drift_rows=drift_rows,
        missing_claims=missing_claim_rows,
        unchanged_rows=unchanged_rows,
    )

    _write_jsonl(args.output_dir / "drift_review_pack.jsonl", drift_rows)
    _write_tsv(args.output_dir / "drift_review_pack.tsv", drift_rows)
    (args.output_dir / "drift_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
