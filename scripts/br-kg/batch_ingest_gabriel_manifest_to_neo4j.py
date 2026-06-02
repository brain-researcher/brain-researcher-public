#!/usr/bin/env python3
"""Batch ingest a Gabriel manifest into Neo4j.

This is an operational fast path for curated/deduped Gabriel manifests. It uses
Gabriel's normalization and gate code, but writes with batched Cypher rather than
the per-record graph adapter path.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)

SCALAR_TYPES = (str, int, float, bool)


def clean_props(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, SCALAR_TYPES):
            out[key] = value
        elif isinstance(value, list) and all(
            isinstance(item, SCALAR_TYPES) for item in value
        ):
            out[key] = value
        else:
            out[key] = json.dumps(value, ensure_ascii=True, sort_keys=True)
    return out


def read_manifest_records(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_dir = manifest_path.resolve().parent
    records: list[dict[str, Any]] = []
    for shard in manifest.get("shards") or []:
        shard_path = Path(str(shard.get("path") or "")).expanduser()
        if not shard_path.is_absolute():
            shard_path = manifest_dir / shard_path
        if not shard_path.is_file():
            raise FileNotFoundError(f"Shard not found: {shard_path}")
        with shard_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        records.append(payload)
    return records


def accepted_by_profile(
    record: dict[str, Any],
    loader: GabrielMeasurementLoader,
) -> tuple[bool, Any, list[str]]:
    variables = compute_gabriel_variables(
        record,
        required_provenance_fields=loader.required_provenance_fields,
    )
    _accepted, reasons = evaluate_high_precision_gate(variables, loader.gate_thresholds)
    reasons = loader._apply_review_only_overrides(
        record,
        variables,
        reasons,
        quality_profile=loader.quality_profile,
    )
    return len(reasons) == 0, variables, list(reasons)


def target_key(target: dict[str, Any]) -> str:
    return "|".join(
        [
            str(target.get("target_type") or ""),
            str(target.get("target_id") or ""),
            str(target.get("target_label") or "").strip().lower(),
        ]
    )


def resolve_target_id(
    session: Any, loader: GabrielMeasurementLoader, target: dict[str, Any]
) -> str:
    target_type = str(target.get("target_type") or "Concept")
    target_id = str(target.get("target_id") or "")
    target_label = str(target.get("target_label") or "").strip()
    label = "Concept" if target_type not in {"Region", "Task"} else target_type

    exact_rows = session.run(
        f"""
        MATCH (n:`{label}` {{id: $target_id}})
        RETURN n.id AS id, coalesce(n.source, "") AS source
        LIMIT 10
        """,
        {"target_id": target_id},
    ).data()
    exact = [
        (str(row["id"]), {"source": str(row.get("source") or "")})
        for row in exact_rows
        if row.get("id")
    ]
    preferred = loader._select_preferred_node_id(exact)
    if preferred:
        return preferred

    if not target_label:
        return target_id

    if label == "Region":
        rows = session.run(
            """
            MATCH (n:Region)
            WHERE toLower(toString(n.name)) = toLower($target_label)
            RETURN n.id AS id, coalesce(n.source, "") AS source
            LIMIT 10
            """,
            {"target_label": target_label},
        ).data()
    elif label == "Task" and not any(
        target_id.startswith(prefix) for prefix in loader.TASK_EXACT_ID_PREFIXES
    ):
        rows = session.run(
            """
            MATCH (n:Task)
            WHERE n.name = $target_label
            RETURN n.id AS id, coalesce(n.source, "") AS source
            LIMIT 10
            """,
            {"target_label": target_label},
        ).data()
    elif label == "Concept":
        rows = session.run(
            """
            MATCH (n:Concept)
            WHERE n.label = $target_label OR n.name = $target_label
            RETURN n.id AS id, coalesce(n.source, "") AS source
            LIMIT 10
            """,
            {"target_label": target_label},
        ).data()
    else:
        rows = []

    candidates = [
        (str(row["id"]), {"source": str(row.get("source") or "")})
        for row in rows
        if row.get("id")
    ]
    return loader._select_preferred_node_id(candidates) or target_id


def resolve_publication_ids(
    session: Any, papers: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Resolve manifest paper IDs to existing Publication IDs where constraints exist."""

    resolved: dict[str, str] = {}
    grouped: dict[tuple[str, str], list[str]] = {}
    for paper_id, paper in papers.items():
        pmid = str(paper.get("pmid") or "").strip()
        doi = str(paper.get("doi") or "").strip().lower()
        pmcid = str(paper.get("pmcid") or "").strip().lower()
        if pmid:
            key = ("pmid", pmid)
        elif doi:
            key = ("doi", doi)
        elif pmcid:
            key = ("pmcid", pmcid)
        else:
            key = ("id", paper_id)
        grouped.setdefault(key, []).append(paper_id)
    for _key, paper_ids in grouped.items():
        canonical = paper_ids[0]
        for paper_id in paper_ids:
            resolved[paper_id] = canonical

    ids = [paper_id for paper_id in papers if paper_id]
    if ids:
        for row in session.run(
            "MATCH (p:Publication) WHERE p.id IN $ids RETURN p.id AS id",
            {"ids": ids},
        ):
            found_id = row.get("id")
            if found_id:
                resolved[str(found_id)] = str(found_id)

    pmid_rows = [
        {"paper_id": paper_id, "pmid": str(paper.get("pmid") or "")}
        for paper_id, paper in papers.items()
        if paper.get("pmid")
    ]
    if pmid_rows:
        rows = session.run(
            """
            UNWIND $rows AS row
            MATCH (p:Publication {pmid: row.pmid})
            SET p.id = coalesce(p.id, row.paper_id)
            RETURN row.paper_id AS paper_id, p.id AS id
            """,
            {"rows": pmid_rows},
        ).data()
        for row in rows:
            if row.get("paper_id") and row.get("id"):
                paper = papers.get(str(row["paper_id"])) or {}
                key = ("pmid", str(paper.get("pmid") or "").strip())
                for paper_id in grouped.get(key, [str(row["paper_id"])]):
                    resolved[paper_id] = str(row["id"])

    doi_rows = [
        {"paper_id": paper_id, "doi": str(paper.get("doi") or "")}
        for paper_id, paper in papers.items()
        if paper.get("doi")
    ]
    if doi_rows:
        rows = session.run(
            """
            UNWIND $rows AS row
            MATCH (p:Publication {doi: row.doi})
            SET p.id = coalesce(p.id, row.paper_id)
            RETURN row.paper_id AS paper_id, p.id AS id
            """,
            {"rows": doi_rows},
        ).data()
        for row in rows:
            if row.get("paper_id") and row.get("id"):
                paper = papers.get(str(row["paper_id"])) or {}
                key = ("doi", str(paper.get("doi") or "").strip().lower())
                for paper_id in grouped.get(key, [str(row["paper_id"])]):
                    resolved[paper_id] = str(row["id"])

    return resolved


def run_batches(
    session: Any, query: str, rows: list[dict[str, Any]], batch_size: int
) -> int:
    total = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        session.run(query, {"rows": batch}).consume()
        total += len(batch)
    return total


def build_rows(
    records: list[dict[str, Any]],
    session: Any,
    *,
    quality_profile: str,
    target_resolution: str,
    promotion_batch: str,
    promotion_status: str,
    release_status: str,
    source_ingest_manifest: str,
    write_targets: bool,
) -> dict[str, Any]:
    loader = GabrielMeasurementLoader(None, config={"quality_profile": quality_profile})
    target_map: dict[str, str] = {}
    targets_by_key: dict[str, dict[str, Any]] = {}

    parsed_records: list[
        tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any]]
    ] = []
    papers_by_id: dict[str, dict[str, Any]] = {}
    rejected = 0
    reject_reasons = Counter()
    for record in records:
        accepted, variables, reasons = accepted_by_profile(record, loader)
        if not accepted:
            rejected += 1
            reject_reasons.update(reasons)
            continue
        paper = loader._extract_paper(record)
        if paper.get("paper_id"):
            papers_by_id.setdefault(str(paper["paper_id"]), paper)
        target = loader._extract_target(record)
        targets_by_key.setdefault(target_key(target), target)
        parsed_records.append((record, variables, paper, target))

    paper_id_map = resolve_publication_ids(session, papers_by_id)

    for key, target in sorted(targets_by_key.items()):
        if target_resolution == "input-id":
            target_map[key] = str(target.get("target_id") or "")
        elif target_resolution == "exact-id":
            target_type = str(target.get("target_type") or "Concept")
            label = "Concept" if target_type not in {"Region", "Task"} else target_type
            target_id = str(target.get("target_id") or "")
            rows = session.run(
                f"""
                MATCH (n:`{label}` {{id: $target_id}})
                RETURN n.id AS id, coalesce(n.source, "") AS source
                LIMIT 10
                """,
                {"target_id": target_id},
            ).data()
            candidates = [
                (str(row["id"]), {"source": str(row.get("source") or "")})
                for row in rows
                if row.get("id")
            ]
            target_map[key] = loader._select_preferred_node_id(candidates) or target_id
        else:
            target_map[key] = resolve_target_id(session, loader, target)

    promotion_props = {
        "promotion_batch": promotion_batch,
        "promotion_status": promotion_status,
        "release_status": release_status,
        "source_ingest_manifest": source_ingest_manifest,
    }

    nodes: dict[str, list[dict[str, Any]]] = {
        "Publication": [],
        "MeasurementRun": [],
        "Concept": [],
        "Region": [],
        "Task": [],
        "Claim": [],
        "EvidenceSpan": [],
        "Assumption": [],
    }
    rels: dict[str, list[dict[str, Any]]] = {
        "MENTIONS": [],
        "MENTIONS_REGION": [],
        "REPORTS_CLAIM": [],
        "SUPPORTS": [],
        "GENERATED": [],
        "ASSUMES": [],
        "CHALLENGES_ASSUMPTION": [],
        "REPLICATES": [],
        "FAILED_REPLICATION_OF": [],
        "NULL_RESULT_FOR": [],
        "CONTRADICTS": [],
        "MAPS_TO": [],
    }

    seen_nodes: set[tuple[str, str]] = set()
    seen_rels: set[tuple[str, str, str]] = set()

    def add_node(label: str, node_id: str, props: dict[str, Any]) -> None:
        if not node_id:
            return
        key = (label, node_id)
        if key in seen_nodes:
            return
        seen_nodes.add(key)
        nodes[label].append(
            {
                "id": node_id,
                "props": clean_props({**props, "id": node_id, "labels": [label]}),
            }
        )

    def add_rel(
        start: str,
        end: str,
        rel_type: str,
        props: dict[str, Any],
        *,
        start_label: str | None = None,
        end_label: str | None = None,
    ) -> None:
        if not start or not end:
            return
        key = (start, rel_type, end)
        if key in seen_rels:
            return
        seen_rels.add(key)
        rels[rel_type].append(
            {
                "start": start,
                "end": end,
                "start_label": start_label,
                "end_label": end_label,
                "props": clean_props(props),
            }
        )

    for record, variables, paper, target in parsed_records:
        original_paper_id = paper["paper_id"]
        paper_id = paper_id_map.get(original_paper_id, original_paper_id)
        if not paper_id:
            continue
        target_id = target_map[target_key(target)]
        run = dict(record.get("run") or {})
        run_id = str(
            run.get("run_id") or record.get("run_id") or loader._hash_record(record)
        )
        run_node_id = f"run:{run_id}"
        claim = loader._extract_claim(record, paper_id, target_id)
        evidence = loader._extract_evidence(record, paper_id, claim["claim_id"])
        assumption = loader._extract_assumption(record, paper_id, claim)
        base_rel_props = loader._build_relationship_properties(
            record,
            run_id,
            variables,
            ingest_annotations=promotion_props,
        )

        add_node(
            "MeasurementRun",
            run_node_id,
            {
                "run_id": run_id,
                "tool": str(run.get("tool") or record.get("tool") or "extract"),
                "model": str(run.get("model") or record.get("model") or "unknown"),
                "prompt_hash": str(
                    run.get("prompt_hash") or record.get("prompt_hash") or "unknown"
                ),
                "template_hash": str(
                    run.get("template_hash") or record.get("template_hash") or "unknown"
                ),
                "raw_response_path": str(
                    run.get("raw_response_path")
                    or record.get("raw_response_path")
                    or "unknown"
                ),
                "status": str(run.get("status") or "completed"),
                "source": "gabriel",
                "provenance_completeness": variables.provenance_completeness,
                **promotion_props,
            },
        )
        add_node(
            "Publication",
            paper_id,
            {
                "title": paper["title"],
                "pmid": paper.get("pmid"),
                "doi": paper.get("doi"),
                "pmcid": paper.get("pmcid"),
                "year": paper.get("year"),
                "journal": paper.get("journal"),
                "source": paper.get("source") or "pubmed",
                "source_paper_id": original_paper_id
                if original_paper_id != paper_id
                else None,
            },
        )
        if write_targets and target_id == target.get("target_id"):
            target_props = loader._target_node_props(
                target_type=target["target_type"],
                target_label=target["target_label"],
                atlas=target.get("atlas"),
            )
            add_node(target["target_type"], target_id, target_props)

        add_node(
            "Claim",
            claim["claim_id"],
            {
                "text": claim["text"],
                "paper_id": paper_id,
                "target_id": target_id,
                "claim_kind": claim["claim_kind"],
                "related_claim_id": claim.get("related_claim_id"),
                "claim_polarity": variables.claim_polarity,
                "claim_strength": variables.claim_strength,
                "method_rigor": variables.method_rigor,
                "main_assumption_text": claim.get("main_assumption_text"),
                "main_assumption_id": claim.get("main_assumption_id"),
                "assumption_type": claim.get("assumption_type"),
                "assumption_scope": claim.get("assumption_scope"),
                "defaultness_score": claim.get("defaultness_score"),
                "challengeability_score": claim.get("challengeability_score"),
                "assumption_confidence": claim.get("assumption_confidence"),
                "assumption_status": claim.get("assumption_status"),
                "provenance_completeness": variables.provenance_completeness,
                "source": "gabriel",
                **promotion_props,
            },
        )
        add_node(
            "EvidenceSpan",
            evidence["span_id"],
            {
                "paper_id": paper_id,
                "claim_id": claim["claim_id"],
                "quote": evidence["quote"],
                "section": evidence.get("section"),
                "page": evidence.get("page"),
                "char_start": evidence.get("char_start"),
                "char_end": evidence.get("char_end"),
                "mention_strength": variables.mention_strength,
                "evidence_quality": variables.evidence_quality,
                "evidence_quality_score": variables.evidence_quality_score,
                "method_rigor": variables.method_rigor,
                "provenance_completeness": variables.provenance_completeness,
                "source": "gabriel",
                **promotion_props,
            },
        )

        if assumption is not None:
            add_node(
                "Assumption",
                assumption["assumption_id"],
                {
                    "text": assumption["text"],
                    "paper_id": paper_id,
                    "source_claim_id": claim["claim_id"],
                    "assumption_type": assumption.get("assumption_type"),
                    "domain_scope": assumption.get("domain_scope"),
                    "defaultness_score": assumption.get("defaultness_score"),
                    "challengeability_score": assumption.get("challengeability_score"),
                    "confidence": assumption.get("confidence"),
                    "status": assumption.get("status"),
                    "source": "gabriel",
                    **promotion_props,
                },
            )

        if write_targets:
            mention_type = (
                "MENTIONS_REGION" if target["target_type"] == "Region" else "MENTIONS"
            )
            add_rel(
                paper_id,
                target_id,
                mention_type,
                base_rel_props,
                start_label="Publication",
                end_label=target["target_type"],
            )
        add_rel(
            paper_id,
            claim["claim_id"],
            "REPORTS_CLAIM",
            base_rel_props,
            start_label="Publication",
            end_label="Claim",
        )
        add_rel(
            evidence["span_id"],
            claim["claim_id"],
            "SUPPORTS",
            base_rel_props,
            start_label="EvidenceSpan",
            end_label="Claim",
        )
        add_rel(
            run_node_id,
            evidence["span_id"],
            "GENERATED",
            base_rel_props,
            start_label="MeasurementRun",
            end_label="EvidenceSpan",
        )
        add_rel(
            run_node_id,
            claim["claim_id"],
            "GENERATED",
            base_rel_props,
            start_label="MeasurementRun",
            end_label="Claim",
        )

        if assumption is not None:
            add_rel(
                claim["claim_id"],
                assumption["assumption_id"],
                "ASSUMES",
                base_rel_props,
                start_label="Claim",
                end_label="Assumption",
            )
            add_rel(
                run_node_id,
                assumption["assumption_id"],
                "GENERATED",
                base_rel_props,
                start_label="MeasurementRun",
                end_label="Assumption",
            )
            if assumption.get("status") == "challenged":
                challenge_props = {
                    **base_rel_props,
                    "challenge_mode": loader._claim_kind_to_challenge_mode(
                        claim["claim_kind"]
                    ),
                }
                add_rel(
                    paper_id,
                    assumption["assumption_id"],
                    "CHALLENGES_ASSUMPTION",
                    challenge_props,
                    start_label="Publication",
                    end_label="Assumption",
                )
                add_rel(
                    claim["claim_id"],
                    assumption["assumption_id"],
                    "CHALLENGES_ASSUMPTION",
                    challenge_props,
                    start_label="Claim",
                    end_label="Assumption",
                )

        relation_type = loader._claim_kind_to_edge_type(claim["claim_kind"])
        related_claim_id = str(claim.get("related_claim_id") or "").strip()
        if relation_type and related_claim_id:
            relation_props = dict(base_rel_props)
            relation_mode = (
                str(claim.get("relation_mode") or "other").strip() or "other"
            )
            if relation_type in {"REPLICATES", "FAILED_REPLICATION_OF"}:
                relation_props["replication_type"] = relation_mode
            elif relation_type == "NULL_RESULT_FOR":
                relation_props["null_result_type"] = relation_mode
            elif relation_type == "CONTRADICTS":
                relation_props["contradiction_scope"] = relation_mode
            add_rel(
                claim["claim_id"],
                related_claim_id,
                relation_type,
                relation_props,
                start_label="Claim",
                end_label="Claim",
            )

        mapping = dict(record.get("mapping") or {})
        canonical_id = mapping.get("canonical_id") or record.get("canonical_id")
        if write_targets and target_id and canonical_id and canonical_id != target_id:
            add_rel(
                target_id,
                str(canonical_id),
                "MAPS_TO",
                {
                    **base_rel_props,
                    "mapping_type": str(mapping.get("mapping_type") or "related"),
                    "similarity_score": variables.mapping_confidence,
                },
                start_label=target["target_type"],
            )

    return {
        "nodes": nodes,
        "relationships": rels,
        "records_input": len(records),
        "records_accepted": len(parsed_records),
        "records_rejected": rejected,
        "reject_reasons": dict(reject_reasons),
        "targets_resolved": sum(
            1
            for key, value in target_map.items()
            if value != targets_by_key[key].get("target_id")
        ),
        "targets_total": len(target_map),
        "publications_resolved": sum(
            1
            for paper_id, resolved_id in paper_id_map.items()
            if paper_id != resolved_id
        ),
        "publications_total": len(paper_id_map),
    }


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    records = read_manifest_records(args.manifest)
    driver = GraphDatabase.driver(
        args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password)
    )
    node_queries = {
        "Publication": "UNWIND $rows AS row MERGE (n:Publication {id: row.id}) SET n += row.props",
        "MeasurementRun": "UNWIND $rows AS row MERGE (n:MeasurementRun {id: row.id}) SET n += row.props",
        "Concept": "UNWIND $rows AS row MERGE (n:Concept {id: row.id}) SET n += row.props",
        "Region": "UNWIND $rows AS row MERGE (n:Region {id: row.id}) SET n += row.props",
        "Task": "UNWIND $rows AS row MERGE (n:Task {id: row.id}) SET n += row.props",
        "Claim": "UNWIND $rows AS row MERGE (n:Claim {id: row.id}) SET n += row.props",
        "EvidenceSpan": "UNWIND $rows AS row MERGE (n:EvidenceSpan {id: row.id}) SET n += row.props",
        "Assumption": "UNWIND $rows AS row MERGE (n:Assumption {id: row.id}) SET n += row.props",
    }
    summary: dict[str, Any] = {}
    with driver:
        driver.verify_connectivity()
        with driver.session() as session:
            rows = build_rows(
                records,
                session,
                quality_profile=args.quality_profile,
                target_resolution=args.target_resolution,
                promotion_batch=args.promotion_batch,
                promotion_status=args.promotion_status,
                release_status=args.release_status,
                source_ingest_manifest=str(args.manifest),
                write_targets=args.write_targets,
            )
            summary.update(
                {
                    key: rows[key]
                    for key in (
                        "records_input",
                        "records_accepted",
                        "records_rejected",
                        "reject_reasons",
                        "targets_resolved",
                        "targets_total",
                        "publications_resolved",
                        "publications_total",
                    )
                }
            )
            summary["nodes"] = {}
            for label, label_rows in rows["nodes"].items():
                if not label_rows:
                    summary["nodes"][label] = 0
                    continue
                if label == "Publication":
                    pmid_rows = [row for row in label_rows if row["props"].get("pmid")]
                    doi_rows = [
                        row
                        for row in label_rows
                        if not row["props"].get("pmid") and row["props"].get("doi")
                    ]
                    id_rows = [
                        row
                        for row in label_rows
                        if not row["props"].get("pmid") and not row["props"].get("doi")
                    ]
                    written = 0
                    if pmid_rows:
                        written += run_batches(
                            session,
                            """
                            UNWIND $rows AS row
                            MERGE (n:Publication {pmid: row.props.pmid})
                            SET n += row.props
                            """,
                            pmid_rows,
                            args.batch_size,
                        )
                    if doi_rows:
                        written += run_batches(
                            session,
                            """
                            UNWIND $rows AS row
                            MERGE (n:Publication {doi: row.props.doi})
                            SET n += row.props
                            """,
                            doi_rows,
                            args.batch_size,
                        )
                    if id_rows:
                        written += run_batches(
                            session,
                            node_queries[label],
                            id_rows,
                            args.batch_size,
                        )
                    summary["nodes"][label] = written
                    continue
                summary["nodes"][label] = run_batches(
                    session, node_queries[label], label_rows, args.batch_size
                )

            summary["relationships"] = {}
            for rel_type, rel_rows in rows["relationships"].items():
                if not rel_rows:
                    summary["relationships"][rel_type] = 0
                    continue
                written = 0
                grouped_rel_rows: dict[
                    tuple[str | None, str | None], list[dict[str, Any]]
                ] = defaultdict(list)
                for row in rel_rows:
                    grouped_rel_rows[
                        (
                            row.get("start_label")
                            if isinstance(row.get("start_label"), str)
                            else None,
                            row.get("end_label")
                            if isinstance(row.get("end_label"), str)
                            else None,
                        )
                    ].append(row)
                for (start_label, end_label), grouped_rows in grouped_rel_rows.items():
                    start_pattern = (
                        f"(a:`{start_label}` {{id: row.start}})"
                        if start_label
                        else "(a {id: row.start})"
                    )
                    end_pattern = (
                        f"(b:`{end_label}` {{id: row.end}})"
                        if end_label
                        else "(b {id: row.end})"
                    )
                    query = (
                        f"UNWIND $rows AS row "
                        f"MATCH {start_pattern} "
                        f"MATCH {end_pattern} "
                        f"MERGE (a)-[r:`{rel_type}`]->(b) "
                        f"SET r += row.props"
                    )
                    written += run_batches(
                        session, query, grouped_rows, args.batch_size
                    )
                summary["relationships"][rel_type] = written
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    )
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    parser.add_argument("--quality-profile", default="kg_bootstrap")
    parser.add_argument(
        "--target-resolution",
        choices=("input-id", "exact-id", "label"),
        default="label",
        help=(
            "How to map record targets before writing claims. label matches loader "
            "semantics but can be slow on large graphs; input-id is fastest and "
            "keeps the candidate layer source-local."
        ),
    )
    parser.add_argument("--promotion-batch", required=True)
    parser.add_argument("--promotion-status", default="candidate_bootstrap")
    parser.add_argument("--release-status", default="not_release_grade")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--write-targets",
        action="store_true",
        help=(
            "Also create target Concept/Region/Task nodes and MENTIONS/MAPS_TO edges. "
            "Leave off for fast candidate-claim promotion when target normalization "
            "will be materialized separately."
        ),
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        help="Optional JSON path for the batch ingest summary/checkpoint.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.neo4j_password:
        raise RuntimeError(
            "Neo4j password missing. Set NEO4J_PASSWORD or pass --neo4j-password."
        )
    summary = ingest(args)
    if args.summary_path:
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        args.summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
