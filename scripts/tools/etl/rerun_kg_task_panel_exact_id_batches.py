#!/usr/bin/env python3
"""Inventory and rerun kg_task_panel manifests that contain exact-id task targets.

This utility discovers task-panel packages under a data root, filters to
non-empty batches that actually contain `task:subfamily:*` or `task:family:*`
targets, and can re-run `br gabriel ingest` with the `kg_task_panel` profile.

It is intentionally task-only:

- it does not inventory `concept:*` reroute subsets
- concept reroutes should not be re-run through ordinary `kg_task_panel` ingest
- concept reroutes should use `migrate_task_panel_exact_ids.py --exact-prefix concept:`

When `--apply` is enabled, it also performs a small live Neo4j verification
sample to confirm claim target ids and `MENTIONS` edges resolve to the exact
target ids carried by the task-panel records.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - optional dependency
    dotenv_values = None

EXACT_ID_PREFIXES = ("task:subfamily:", "task:family:")


@dataclass
class Candidate:
    package_summary_path: str
    manifest_path: str
    task_panel_records_path: str
    task_fold_mode: str | None
    task_records_kept: int
    task_records_family_matched: int | None
    task_ids_canonical_total: int | None
    exact_id_records_count: int


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_exact_id_records(records_path: Path) -> int:
    count = 0
    if not records_path.exists():
        return count
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            target_id = str((row.get("target") or {}).get("id") or "").strip()
            if target_id.startswith(EXACT_ID_PREFIXES):
                count += 1
    return count


def discover_candidates(root: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for summary_path in sorted(root.rglob("package_summary.json")):
        if "task_panel" not in str(summary_path):
            continue
        data = _load_json(summary_path)
        counts = data.get("counts") or {}
        artifacts = data.get("artifacts") or {}
        inputs = data.get("inputs") or {}
        manifest_path = artifacts.get("manifest_task_panel")
        records_path = artifacts.get("task_panel_records")
        kept = int(counts.get("task_records_kept") or 0)
        if not manifest_path or not records_path or kept <= 0:
            continue
        exact_id_records = _count_exact_id_records(Path(records_path))
        if exact_id_records <= 0:
            continue
        candidates.append(
            Candidate(
                package_summary_path=str(summary_path),
                manifest_path=str(manifest_path),
                task_panel_records_path=str(records_path),
                task_fold_mode=(
                    str(inputs.get("task_fold_mode")).strip()
                    if inputs.get("task_fold_mode") is not None
                    else None
                ),
                task_records_kept=kept,
                task_records_family_matched=(
                    int(counts.get("task_records_family_matched"))
                    if counts.get("task_records_family_matched") is not None
                    else None
                ),
                task_ids_canonical_total=(
                    int(counts.get("task_ids_canonical_total"))
                    if counts.get("task_ids_canonical_total") is not None
                    else None
                ),
                exact_id_records_count=exact_id_records,
            )
        )
    return candidates


def _candidate_sort_key(candidate: Candidate) -> tuple[int, int, str]:
    family_matched = candidate.task_records_family_matched or 0
    return (-candidate.task_records_kept, -family_matched, candidate.manifest_path)


def _load_env_with_dotenv() -> dict[str, str]:
    env = dict(os.environ)
    env_path = Path(".env")
    if dotenv_values is not None and env_path.exists():
        for key, value in dotenv_values(env_path).items():
            if value is not None:
                env.setdefault(str(key), str(value))
    return env


def _extract_json_tail(text: str) -> dict[str, Any] | None:
    lines = [line for line in text.splitlines() if line.strip()]
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads("\n".join(lines[idx:]))
        except json.JSONDecodeError:
            continue
    return None


def run_ingest(manifest_path: Path, env: dict[str, str]) -> dict[str, Any]:
    command = [
        "br",
        "gabriel",
        "ingest",
        "--manifest",
        str(manifest_path),
        "--quality-profile",
        "kg_task_panel",
        "--no-resume",
        "--json",
    ]
    completed = subprocess.run(
        command,
        cwd=str(Path.cwd()),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": _extract_json_tail(completed.stdout),
    }
    return payload


def _sample_exact_id_rows(records_path: Path, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            target_id = str((record.get("target") or {}).get("id") or "").strip()
            if not target_id.startswith(EXACT_ID_PREFIXES):
                continue
            claim_id = str((record.get("claim") or {}).get("id") or "").strip()
            paper_id = str((record.get("paper") or {}).get("id") or "").strip()
            run_id = str((record.get("run") or {}).get("run_id") or "").strip()
            if not claim_id or not paper_id or not run_id:
                continue
            rows.append(
                {
                    "claim_id": claim_id,
                    "paper_id": paper_id,
                    "run_id": run_id,
                    "target_id": target_id,
                }
            )
            if len(rows) >= limit:
                break
    return rows


def verify_exact_id_sample(
    env: dict[str, str],
    records_path: Path,
    *,
    sample_size: int,
) -> dict[str, Any]:
    rows = _sample_exact_id_rows(records_path, sample_size)
    if not rows:
        return {
            "sample_size_requested": sample_size,
            "sample_size_actual": 0,
            "matches_all": True,
            "rows": [],
        }

    uri = env.get("NEO4J_URI")
    user = env.get("NEO4J_USER")
    password = env.get("NEO4J_PASSWORD")
    database = env.get("NEO4J_DATABASE") or "neo4j"
    if not uri or not user or not password:
        raise RuntimeError("Missing Neo4j connection settings in environment/.env")

    def cypher_quote(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    literal_rows = ",\n  ".join(
        (
            "{"
            f"claim_id:'{cypher_quote(row['claim_id'])}', "
            f"paper_id:'{cypher_quote(row['paper_id'])}', "
            f"run_id:'{cypher_quote(row['run_id'])}', "
            f"target_id:'{cypher_quote(row['target_id'])}'"
            "}"
        )
        for row in rows
    )
    query = f"""
    UNWIND [
      {literal_rows}
    ] AS row
    MATCH (c:Claim {{id: row.claim_id}})
    OPTIONAL MATCH (:Publication {{id: row.paper_id}})-[m:MENTIONS {{run_id: row.run_id}}]->(:Task {{id: row.target_id}})
    RETURN row.claim_id AS claim_id,
           row.paper_id AS paper_id,
           row.run_id AS run_id,
           row.target_id AS expected_target_id,
           c.target_id AS actual_target_id,
           count(m) AS mention_count
    ORDER BY claim_id
    """
    completed = subprocess.run(
        [
            "cypher-shell",
            "-a",
            uri,
            "-u",
            user,
            "-p",
            password,
            "-d",
            database,
            "--format",
            "plain",
        ],
        cwd=str(Path.cwd()),
        env=env,
        input=query,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "cypher-shell verification failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )

    reader = csv.DictReader(
        [line for line in completed.stdout.splitlines() if line.strip()],
        skipinitialspace=True,
    )
    payload_rows = []
    for record in reader:
        payload_rows.append(
            {
                "claim_id": record.get("claim_id"),
                "paper_id": record.get("paper_id"),
                "run_id": record.get("run_id"),
                "expected_target_id": record.get("expected_target_id"),
                "actual_target_id": record.get("actual_target_id"),
                "mention_count": int(record.get("mention_count") or 0),
            }
        )

    matches_all = all(
        row.get("actual_target_id") == row.get("expected_target_id")
        and int(row.get("mention_count") or 0) >= 1
        for row in payload_rows
    )
    return {
        "sample_size_requested": sample_size,
        "sample_size_actual": len(payload_rows),
        "matches_all": matches_all,
        "rows": payload_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory and rerun exact-id kg_task_panel manifests for task-only "
            "exact targets. Concept reroutes are excluded and should use "
            "migrate_task_panel_exact_ids.py with --exact-prefix concept:."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/neurokg/raw/gabriel"),
        help="Root directory to scan for task panel packages.",
    )
    parser.add_argument(
        "--min-kept",
        type=int,
        default=1,
        help="Only include manifests with at least this many kept task records.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit selected manifests after sorting (0 means no limit).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Re-run ingest for selected manifests.",
    )
    parser.add_argument(
        "--verify-sample-size",
        type=int,
        default=20,
        help="Number of exact-id rows to sample per manifest after rerun.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates = discover_candidates(args.root)
    selected = [
        candidate
        for candidate in sorted(candidates, key=_candidate_sort_key)
        if candidate.task_records_kept >= args.min_kept
    ]
    if args.limit > 0:
        selected = selected[: args.limit]

    print(
        json.dumps(
            {
                "root": str(args.root),
                "apply": bool(args.apply),
                "selected_count": len(selected),
                "candidates": [asdict(candidate) for candidate in selected],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not args.apply:
        return 0

    env = _load_env_with_dotenv()
    results: list[dict[str, Any]] = []
    for candidate in selected:
        ingest_result = run_ingest(Path(candidate.manifest_path), env)
        verify_result: dict[str, Any]
        if ingest_result["returncode"] != 0:
            verify_result = {
                "sample_size_requested": args.verify_sample_size,
                "sample_size_actual": 0,
                "matches_all": False,
                "rows": [],
                "error": "ingest_failed",
            }
        else:
            try:
                verify_result = verify_exact_id_sample(
                    env,
                    Path(candidate.task_panel_records_path),
                    sample_size=args.verify_sample_size,
                )
            except Exception as exc:  # pragma: no cover - operational fallback
                verify_result = {
                    "sample_size_requested": args.verify_sample_size,
                    "sample_size_actual": 0,
                    "matches_all": False,
                    "rows": [],
                    "error": str(exc),
                }

        results.append(
            {
                "candidate": asdict(candidate),
                "ingest": {
                    "returncode": ingest_result["returncode"],
                    "json": ingest_result["json"],
                    "stderr": ingest_result["stderr"].strip(),
                },
                "verify": verify_result,
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    any_failures = any(
        result["ingest"]["returncode"] != 0 or not result["verify"]["matches_all"]
        for result in results
    )
    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
