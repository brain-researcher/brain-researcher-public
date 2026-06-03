"""Load fMRI statistical-methodology Concept nodes into BR-KG.

Motivation: BR-KG has Concept/Task/Region/Dataset/Publication nodes but NO nodes for
statistical-methodology terms (double dipping, cluster-defining threshold, FWE/FDR,
multiple comparisons, GSR, ...). On methodology questions the KG returns 0 hits, so
grounding for those claims has no KG path. The terms already exist as review-rule
metadata in ``data/neuro_methods_kb.yaml``; this loader mints idempotent Concept nodes
(label ``Concept`` + ``MethodConcept``) from them, with the rule keywords as aliases so
``kg_search_nodes`` can match them.

Idempotent: ``create_node`` MERGEs on ``id`` so re-running updates rather than duplicates.

CLI (does NOT run automatically — invoke explicitly):
    python -m brain_researcher.services.br_kg.etl.loaders.fmri_methods_concept_loader \
        --yaml data/neuro_methods_kb.yaml [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_concept_records(yaml_path: str | Path) -> list[dict[str, Any]]:
    """Parse neuro_methods_kb.yaml into Concept node property dicts (pure, no DB)."""
    import yaml

    rules = yaml.safe_load(Path(yaml_path).read_text()) or []
    records: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("id"):
            continue
        triggers = rule.get("triggers") or {}
        keywords = [str(k) for k in (triggers.get("query_keywords") or []) if str(k).strip()]
        records.append(
            {
                "id": f"method_{rule['id']}",
                "name": str(rule.get("title") or rule["id"]),
                "aliases": keywords,
                "category": "statistical_methodology",
                "severity": rule.get("severity"),
                "actionable_fix": rule.get("actionable_fix"),
                "needs_citation": bool(rule.get("needs_citation")),
                "source": "neuro_methods_kb.yaml",
            }
        )
    return records


def load(db: Any, yaml_path: str | Path) -> dict[str, Any]:
    """Create/MERGE Concept(+MethodConcept) nodes from the methods KB. Returns a summary."""
    records = build_concept_records(yaml_path)
    created = []
    for rec in records:
        node_id = db.create_node(["Concept", "MethodConcept"], rec, node_id=rec["id"])
        created.append(node_id)
    return {"loaded": len(created), "ids": created}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", default="data/neuro_methods_kb.yaml")
    ap.add_argument("--dry-run", action="store_true", help="parse + print records, do NOT touch the DB")
    args = ap.parse_args(argv)

    records = build_concept_records(args.yaml)
    if args.dry_run:
        print(json.dumps({"would_load": len(records), "records": records}, indent=2))
        return 0

    from brain_researcher.services.br_kg.db.bootstrap import get_db

    db = get_db()
    summary = load(db, args.yaml)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
