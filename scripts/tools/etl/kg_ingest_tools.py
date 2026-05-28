"""
Ingest agent tool/intent data into Neo4j.

Requires env:
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

Usage:
  python scripts/tools/etl/kg_ingest_tools.py [--dry-run]

Env:
  BR_NIWRAP_LIMIT      cap NiWrap tools during ingest
  NEO4J_DATABASE       optional, defaults to Neo4j default DB

When --dry-run is set, the script performs extraction only and prints
aggregate counts plus recommended verification Cypher queries; it does
not write to Neo4j. This is useful to catch catalog explosions (e.g.,
unexpected BELONGS_TO_FAMILY edges) before mutating the graph.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml
from neo4j import GraphDatabase

from scripts.tools.etl.kg_extract_tools import (
    aggregate_family_ops,
    extract_operations,
    extract_synonyms,
    extract_tools_and_families,
)

# -----------------------------
# Verification helpers
# -----------------------------


VERIFICATION_QUERIES = [
    {
        "name": "tool_count",
        "cypher": "MATCH (t:Tool) RETURN count(t) AS tool_count",
    },
    {
        "name": "family_count",
        "cypher": "MATCH (f:ToolFamily) RETURN count(f) AS family_count",
    },
    {
        "name": "belongs_edges",
        "cypher": "MATCH (:Tool)-[r:BELONGS_TO_FAMILY]->(:ToolFamily) RETURN count(r) AS rel_count",
    },
    {
        "name": "top_families",
        "cypher": (
            "MATCH (f:ToolFamily)<-[:BELONGS_TO_FAMILY]-(t:Tool) "
            "RETURN f.id AS family, count(t) AS tool_count "
            "ORDER BY tool_count DESC LIMIT 10"
        ),
    },
    {
        "name": "duplicate_family_edges",
        "cypher": (
            "MATCH (t:Tool)-[r:BELONGS_TO_FAMILY]->(f:ToolFamily) "
            "WITH t.id AS tid, f.id AS fid, count(r) AS c "
            "WHERE c > 1 RETURN tid, fid, c ORDER BY c DESC LIMIT 20"
        ),
    },
    {
        "name": "tools_missing_family",
        "cypher": (
            "MATCH (t:Tool) WHERE NOT (t)-[:BELONGS_TO_FAMILY]->() "
            "RETURN t.id AS tool_id LIMIT 20"
        ),
    },
    # Data integrity checks (Phase 3)
    {
        "name": "orphan_tool_versions",
        "cypher": (
            "MATCH (v:ToolVersion) WHERE NOT (v)<-[:HAS_VERSION]-(:Tool) "
            "RETURN v.version_id AS orphan_version LIMIT 20"
        ),
    },
    {
        "name": "tools_missing_version",
        "cypher": (
            "MATCH (t:Tool) WHERE NOT (t)-[:HAS_VERSION]->(:ToolVersion) "
            "RETURN t.tool_id AS tool_without_version LIMIT 20"
        ),
    },
    {
        "name": "duplicate_version_ids",
        "cypher": (
            "MATCH (v:ToolVersion) WITH v.version_id AS vid, count(*) AS cnt "
            "WHERE cnt > 1 RETURN vid, cnt ORDER BY cnt DESC LIMIT 10"
        ),
    },
    {
        "name": "resource_edge_counts",
        "cypher": (
            "MATCH (:ToolVersion)-[r:CONSUMES_RESOURCE|PRODUCES_RESOURCE]->(:ResourceType) "
            "RETURN type(r) AS rel_type, count(r) AS count"
        ),
    },
    {
        "name": "tool_version_counts",
        "cypher": "MATCH (v:ToolVersion) RETURN count(v) AS version_count",
    },
]


def print_verification_queries():
    print("Recommended Cypher checks (run in Neo4j Browser or cypher-shell):")
    for q in VERIFICATION_QUERIES:
        print(f"\n-- {q['name']}\n{q['cypher']}")


def ingest_operations(tx, ops, children):
    tx.run(
        """
        UNWIND $ops AS op
        MERGE (o:Operation {id: op.id})
          SET o.name = op.name,
              o.description = op.description,
              o.domains = op.domains,
              o.modalities = op.modalities,
              o.analysis_level = op.analysis_level,
              o.source = 'agent_intents/v1'
        """,
        ops=ops,
    )
    tx.run(
        """
        UNWIND $children AS rel
        MATCH (p:Operation {id: rel.parent})
        MATCH (c:Operation {id: rel.child})
        MERGE (p)-[:PARENT_OF]->(c)
        """,
        children=[{"parent": p, "child": c} for p, c in children],
    )


def ingest_operation_modalities(tx, ops):
    """Create Modality nodes and link operations to them."""
    rows = []
    for op in ops:
        for mod in op.get("modalities", []) or []:
            rows.append({"op": op["id"], "mod": mod})
    if not rows:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (m:Modality {id: row.mod})
          ON CREATE SET m.name = row.mod
        WITH m, row
        MATCH (o:Operation {id: row.op})
        MERGE (o)-[:FOR_MODALITY]->(m)
        """,
        rows=rows,
    )


def create_vector_indexes(tx):
    # Create vector indexes for embeddings if not exist (384 dims, cosine)
    tx.run(
        """
        CREATE VECTOR INDEX tool_embedding_idx IF NOT EXISTS
        FOR (t:Tool) ON (t.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 384,
            `vector.similarity_function`: 'cosine'
        }}
        """
    )
    tx.run(
        """
        CREATE VECTOR INDEX tool_embedding_v2_idx IF NOT EXISTS
        FOR (t:Tool) ON (t.embedding_v2)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 384,
            `vector.similarity_function`: 'cosine'
        }}
        """
    )


def ingest_synonyms(tx, synonyms):
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (o:Operation {id: row.operation_id})
        MERGE (s:OperationSynonym {text: row.text})
          SET s.lang = row.lang,
              s.kind = row.kind,
              s.source = row.source
        MERGE (s)-[:ALIAS_OF]->(o)
        """,
        rows=synonyms,
    )


def ingest_families(tx, families):
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (f:ToolFamily {id: row.id})
          SET f.name = row.name,
              f.runtime_kinds = row.runtime_kinds,
              f.packages = row.packages,
              f.source = row.source
        """,
        rows=families,
    )


def ingest_tools(tx, tools):
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (t:Tool {id: row.id})
          SET t.name = row.name,
              t.tool_id = row.id,
              t.package = row.package,
              t.runtime_kind = row.runtime_kind,
              t.entrypoint = row.entrypoint,
              t.modality = row.modality,
              t.family_ids = coalesce(row.family_ids, [row.family_id]),
              t.is_niwrap = row.is_niwrap,
              t.is_promoted = row.is_promoted,
              t.is_curated = row.is_curated,
              t.source = row.source,
              t.description = row.description,
              t.capabilities = row.capabilities,
              t.consumes = row.consumes,
              t.produces = row.produces,
              t.cpu_min = row.cpu_min,
              t.mem_mb_min = row.mem_mb_min,
              t.gpu = row.gpu,
              t.time_min_default = row.time_min_default,
              t.stage = row.stage,
              t.cost_tier = row.cost_tier,
              t.origin = row.origin,
              t.lifecycle = row.lifecycle,
              t.recipe_family = row.recipe_family,
              t.stable_workflow_pack = row.stable_workflow_pack,
              t.source_repo = row.source_repo,
              t.source_paper = row.source_paper,
              t.tested_release = row.tested_release,
              t.reference_assets = row.reference_assets,
              t.backend_options_available = row.backend_options_available,
              t.backend_default = row.backend_default,
              t.example_dataset_id = row.example_dataset_id,
              t.runbook = row.runbook,
              t.artifact_required_outputs = row.artifact_required_outputs,
              t.artifact_optional_outputs = row.artifact_optional_outputs,
              t.artifact_report_files = row.artifact_report_files,
              t.execution_recipe_available = row.execution_recipe_available,
              t.execution_story_kind = row.execution_story_kind,
              t.execution_story = row.execution_story,
              t.supported_recipe_targets = row.supported_recipe_targets,
              t.primary_target = row.primary_target,
              t.canonical_tool_id = row.canonical_tool_id,
              t.recipe_depth = row.recipe_depth,
              t.hosted_via_br_mcp_service = row.hosted_via_br_mcp_service,
              t.recipe_first_workflow = row.recipe_first_workflow,
              t.heavy_runtime_workflow = row.heavy_runtime_workflow,
              t.batch_analysis_workflow = row.batch_analysis_workflow,
              t.workflow_surface_class = row.workflow_surface_class,
              t.mcp_execution_posture = row.mcp_execution_posture,
              t.direct_tool_execution_supported = row.direct_tool_execution_supported,
              t.manual_pipeline_execution_only = row.manual_pipeline_execution_only,
              t.recommended_mcp_entrypoint = row.recommended_mcp_entrypoint,
              t.execution_guidance = row.execution_guidance,
              t.neurodesk_package_name = row.neurodesk_package_name,
              t.neurodesk_module_name = row.neurodesk_module_name,
              t.neurodesk_recommended_version = row.neurodesk_recommended_version,
              t.neurodesk_recommended_module = row.neurodesk_recommended_module
        WITH t, coalesce(row.family_ids, [row.family_id]) AS family_ids
        UNWIND family_ids AS family_id
        MATCH (f:ToolFamily {id: family_id})
        MERGE (t)-[:BELONGS_TO_FAMILY]->(f)
        """,
        rows=tools,
    )

    tx.run(
        """
        UNWIND $rows AS row
        MATCH (t:Tool {id: row.id})
        UNWIND row.intents AS intent_id
        MATCH (o:Operation {id: intent_id})
        MERGE (t)-[:IMPLEMENTS]->(o)
        """,
        rows=[
            {"id": t["id"], "intents": t["intents"]} for t in tools if t.get("intents")
        ],
    )


def ingest_resource_types(tx, tools):
    """Create ResourceType nodes and CONSUMES/PRODUCES relationships."""
    # Collect all resource types
    consumes_rows = []
    produces_rows = []
    for t in tools:
        for res in t.get("consumes", []) or []:
            consumes_rows.append({"tool_id": t["id"], "resource": res})
        for res in t.get("produces", []) or []:
            produces_rows.append({"tool_id": t["id"], "resource": res})

    if consumes_rows:
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (r:ResourceType {id: row.resource})
              ON CREATE SET r.name = row.resource
            WITH r, row
            MATCH (t:Tool {id: row.tool_id})
            MERGE (t)-[:CONSUMES]->(r)
            """,
            rows=consumes_rows,
        )

    if produces_rows:
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (r:ResourceType {id: row.resource})
              ON CREATE SET r.name = row.resource
            WITH r, row
            MATCH (t:Tool {id: row.tool_id})
            MERGE (t)-[:PRODUCES]->(r)
            """,
            rows=produces_rows,
        )


def ingest_family_ops(tx, fam_ops):
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (f:ToolFamily {id: row.family_id})
        MATCH (o:Operation {id: row.operation_id})
        MERGE (f)-[r:IMPLEMENTS]->(o)
          SET r.tool_count = row.tool_count
        """,
        rows=fam_ops,
    )


def ingest_pipeline_templates(tx, pipelines):
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (p:PipelineTemplate {id: row.id})
          SET p.name = row.name,
              p.description = row.description,
              p.source = 'kg_mapping_pipeline_templates'
        """,
        rows=pipelines,
    )

    # Pipeline -> Operation steps
    rel_rows = []
    for p in pipelines:
        for op in p.get("operations", []):
            rel_rows.append({"pid": p["id"], "op": op})
    if rel_rows:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (p:PipelineTemplate {id: row.pid})
            MATCH (o:Operation {id: row.op})
            MERGE (p)-[:HAS_STEP]->(o)
            """,
            rows=rel_rows,
        )

    # Pipeline -> preferred families
    pref_rows = []
    for p in pipelines:
        for fam in p.get("prefer_families", []):
            pref_rows.append({"pid": p["id"], "fam": fam})
        if pref_rows:
            tx.run(
                """
                UNWIND $rows AS row
                MATCH (p:PipelineTemplate {id: row.pid})
                MATCH (f:ToolFamily {id: row.fam})
                MERGE (p)-[:USES_FAMILY]->(f)
                """,
                rows=pref_rows,
            )


def ingest_pipeline_dataset_recs(tx, recs):
    """Create DatasetFamily nodes and link pipelines to them."""
    if not recs:
        return
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (d:DatasetFamily {id: row.dataset_family})
          ON CREATE SET d.name = row.dataset_family
        WITH d, row
        MATCH (p:PipelineTemplate {id: row.pipeline_id})
        MERGE (p)-[:RECOMMENDED_FOR]->(d)
        """,
        rows=recs,
    )


def main():
    parser = argparse.ArgumentParser(description="Ingest agent tools into Neo4j")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and show counts/queries without writing to Neo4j",
    )
    args = parser.parse_args()

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE")

    ops, children = extract_operations()
    synonyms = extract_synonyms()
    families, tools = extract_tools_and_families()
    fam_ops = aggregate_family_ops(tools)
    # load pipeline templates mapping (optional)
    mapping_path = (
        Path(__file__).resolve().parent / "kg_mapping_pipeline_templates.yaml"
    )
    pipelines = []
    if mapping_path.exists():
        raw = yaml.safe_load(mapping_path.read_text()) or {}
        pipelines = raw.get("pipelines", [])
        # allow dict form (name -> fields)
        if isinstance(pipelines, dict):
            pipelines = list(pipelines.values())

    # Optional pipeline -> dataset family recommendations
    dataset_rec_path = (
        Path(__file__).resolve().parent / "kg_mapping_pipeline_datasets.yaml"
    )
    dataset_recs = []
    if dataset_rec_path.exists():
        dataset_recs = yaml.safe_load(dataset_rec_path.read_text()) or []

    if args.dry_run:
        print("-- DRY RUN: extraction only, no writes --")
        print(
            f"extracted: ops={len(ops)} syns={len(synonyms)} families={len(families)} "
            f"tools={len(tools)} fam_ops={len(fam_ops)}"
            + (f" pipelines={len(pipelines)}" if pipelines else "")
            + (f" dataset_recs={len(dataset_recs)}" if dataset_recs else "")
        )
        print_verification_queries()
        return

    driver = GraphDatabase.driver(uri, auth=(user, password))
    session_kwargs = {"database": database} if database else {}
    with driver.session(**session_kwargs) as session:
        session.execute_write(ingest_operations, ops, children)
        session.execute_write(ingest_synonyms, synonyms)
        session.execute_write(ingest_families, families)
        session.execute_write(ingest_tools, tools)
        session.execute_write(ingest_resource_types, tools)
        session.execute_write(ingest_family_ops, fam_ops)
        if pipelines:
            session.execute_write(ingest_pipeline_templates, pipelines)
        if dataset_recs:
            session.execute_write(ingest_pipeline_dataset_recs, dataset_recs)
        # Link operations to modalities (broad KG link)
        session.execute_write(ingest_operation_modalities, ops)
        # Ensure vector indexes exist for embeddings
        session.execute_write(create_vector_indexes)

    print(
        f"Ingest complete: ops={len(ops)} syns={len(synonyms)} "
        f"families={len(families)} tools={len(tools)} fam_ops={len(fam_ops)}"
        + (f" pipelines={len(pipelines)}" if pipelines else "")
        + (f" dataset_recs={len(dataset_recs)}" if dataset_recs else "")
    )


if __name__ == "__main__":
    main()
