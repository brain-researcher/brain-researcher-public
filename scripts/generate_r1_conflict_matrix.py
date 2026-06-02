#!/usr/bin/env python3
"""Generate an R1 conflict-mapping artifact from structured evidence records.

Input evidence JSON format (list):
[
  {
    "id": "paper_1",
    "condition": {
      "task_type": "cognitive",
      "population": "healthy",
      "method": "fMRI"
    },
    "conclusion": "supports_conflict" | "supports_pain" | "conditional" | "insufficient",
    "notes": "optional text",
    "provenance": "optional source URI"
  }
]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

try:
    import yaml
except Exception:  # pragma: no cover - yaml dependency is optional
    yaml = None


SUPPORTED_CONCLUSIONS = {
    "supports_conflict",
    "supports_pain",
    "conditional",
    "insufficient",
}


@dataclass(frozen=True)
class RowKey:
    task_type: str
    population: str
    method: str

    @property
    def id(self) -> str:
        return (
            f"task={self.task_type}|population={self.population}|method={self.method}"
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize(value: Any, fallback: str = "unspecified") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def parse_evidence(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Evidence input must be a JSON list")
    normalized: List[Dict[str, Any]] = []
    for idx, record in enumerate(payload):
        if not isinstance(record, dict):
            continue
        condition = record.get("condition") or {}
        if not isinstance(condition, dict):
            condition = {}
        conclusion = normalize(record.get("conclusion"), "insufficient")
        if conclusion not in SUPPORTED_CONCLUSIONS:
            conclusion = "insufficient"
        normalized.append(
            {
                "id": normalize(record.get("id"), f"evidence_{idx+1}"),
                "condition": {
                    "task_type": normalize(condition.get("task_type")),
                    "population": normalize(condition.get("population")),
                    "method": normalize(condition.get("method")),
                },
                "conclusion": conclusion,
                "notes": normalize(record.get("notes"), ""),
                "provenance": normalize(record.get("provenance"), ""),
            }
        )
    return normalized


def group_by_row(records: Iterable[Dict[str, Any]]) -> Dict[RowKey, List[Dict[str, Any]]]:
    grouped: Dict[RowKey, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        cond = record["condition"]
        key = RowKey(
            task_type=normalize(cond.get("task_type")),
            population=normalize(cond.get("population")),
            method=normalize(cond.get("method")),
        )
        grouped[key].append(record)
    return grouped


def entropy(counts: Mapping[str, int]) -> float:
    import math

    total = sum(counts.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for value in counts.values():
        if value <= 0:
            continue
        p = value / total
        h -= p * math.log2(p)
    return h


def rank_moderators(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    overall = Counter(record["conclusion"] for record in records)
    base_entropy = entropy(overall)
    moderators = ["task_type", "population", "method"]
    ranked: List[Tuple[str, float, Dict[str, Dict[str, int]]]] = []

    for moderator in moderators:
        grouped: Dict[str, Counter[str]] = defaultdict(Counter)
        for record in records:
            grouped[record["condition"][moderator]][record["conclusion"]] += 1
        total = sum(sum(counter.values()) for counter in grouped.values()) or 1
        conditional_entropy = 0.0
        details: Dict[str, Dict[str, int]] = {}
        for label, counter in grouped.items():
            n = sum(counter.values())
            conditional_entropy += (n / total) * entropy(counter)
            details[label] = dict(counter)
        info_gain = max(0.0, base_entropy - conditional_entropy)
        ranked.append((moderator, info_gain, details))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [
        {
            "moderator": moderator,
            "information_gain": round(score, 4),
            "distribution_by_level": details,
        }
        for moderator, score, details in ranked
    ]


def build_output(
    *,
    claim: str,
    scope: str,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    grouped = group_by_row(records)

    matrix_rows: List[Dict[str, Any]] = []
    for key, entries in sorted(grouped.items(), key=lambda item: item[0].id):
        counts = Counter(entry["conclusion"] for entry in entries)
        matrix_rows.append(
            {
                "row_id": key.id,
                "conditions": {
                    "task_type": key.task_type,
                    "population": key.population,
                    "method": key.method,
                },
                "counts": {
                    "supports_conflict": counts.get("supports_conflict", 0),
                    "supports_pain": counts.get("supports_pain", 0),
                    "conditional": counts.get("conditional", 0),
                    "insufficient": counts.get("insufficient", 0),
                },
                "evidence_ids": [entry["id"] for entry in entries],
            }
        )

    true_conflicts: List[Dict[str, Any]] = []
    conditional_agreements: List[Dict[str, Any]] = []
    for row in matrix_rows:
        c = row["counts"]
        has_conflict_and_pain = c["supports_conflict"] > 0 and c["supports_pain"] > 0
        has_conditional = c["conditional"] > 0
        if has_conflict_and_pain:
            true_conflicts.append(
                {
                    "row_id": row["row_id"],
                    "conditions": row["conditions"],
                    "counts": c,
                }
            )
        elif has_conditional:
            conditional_agreements.append(
                {
                    "row_id": row["row_id"],
                    "conditions": row["conditions"],
                    "counts": c,
                }
            )

    return {
        "schema_version": "r1_conflict_mapping_output_v1",
        "generated_at": utc_now_iso(),
        "claim": claim,
        "scope": scope,
        "n_evidence_records": len(records),
        "condition_conclusion_matrix": matrix_rows,
        "key_moderators_ranked": rank_moderators(records),
        "true_conflicts": true_conflicts,
        "conditional_agreements": conditional_agreements,
        "provenance_index": [
            {
                "id": record["id"],
                "conclusion": record["conclusion"],
                "condition": record["condition"],
                "notes": record["notes"],
                "provenance": record["provenance"],
            }
            for record in records
        ],
    }


def write_output(payload: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
        output_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        return
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate R1 conflict matrix output.")
    parser.add_argument("--evidence-json", required=True, type=Path)
    parser.add_argument("--claim", required=True, type=str)
    parser.add_argument("--scope", default="unspecified", type=str)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    records = parse_evidence(args.evidence_json)
    payload = build_output(claim=args.claim, scope=args.scope, records=records)
    write_output(payload, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": len(records),
                "rows": len(payload["condition_conclusion_matrix"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
