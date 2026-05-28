"""
Generate semantic embeddings for Tool nodes and store in Neo4j.

Usage:
  python scripts/tools/etl/kg_embed_tools.py     [--model gemini|sentence-transformer]     [--batch-size 100]     [--limit 10000]     [--embedding-field embedding|embedding_v2]     [--use-file-search]     [--file-search-store fileSearchStores/...]

This script:
1. Fetches all Tool nodes from Neo4j that don't have embeddings
2. Generates embeddings using the specified model
3. Stores embeddings back in Neo4j

Environment:
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
  GOOGLE_API_KEY (for Gemini embeddings)
"""

from __future__ import annotations

import argparse
import logging
import os

import numpy as np
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


def get_embedding_model(model_type: str = "sentence-transformer"):
    """Get the appropriate embedding model."""
    if model_type == "gemini":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            return GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=os.environ.get("GOOGLE_API_KEY"),
            )
        except ImportError:
            logger.warning(
                "langchain_google_genai not installed, falling back to sentence-transformer"
            )
            model_type = "sentence-transformer"

    if model_type == "sentence-transformer":
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2")

    raise ValueError(f"Unknown model type: {model_type}")


def embed_texts(model, texts: list[str], model_type: str) -> np.ndarray:
    """Generate embeddings for a batch of texts."""
    if model_type == "gemini":
        embeddings = model.embed_documents(texts)
        return np.array(embeddings, dtype="float32")
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def get_tools_without_embeddings(
    session, field: str = "embedding", limit: int = 1000
) -> list[dict]:
    """Fetch Tool nodes that don't have the given embedding field yet."""
    result = session.run(
        f"""
        MATCH (t:Tool)
        WHERE t.{field} IS NULL
        RETURN t.id AS id,
               t.name AS name,
               t.description AS description,
               t.capabilities AS capabilities,
               t.package AS package,
               t.intents AS intents,
               t.consumes AS consumes,
               t.produces AS produces,
               t.stage AS stage,
               t.cost_tier AS cost_tier,
               t.lifecycle AS lifecycle,
               t.recipe_family AS recipe_family,
               t.execution_story_kind AS execution_story_kind,
               t.supported_recipe_targets AS supported_recipe_targets,
               t.primary_target AS primary_target,
               t.recipe_first_workflow AS recipe_first_workflow,
               t.heavy_runtime_workflow AS heavy_runtime_workflow,
               t.batch_analysis_workflow AS batch_analysis_workflow,
               t.workflow_surface_class AS workflow_surface_class,
               t.mcp_execution_posture AS mcp_execution_posture,
               t.recommended_mcp_entrypoint AS recommended_mcp_entrypoint,
               t.execution_guidance AS execution_guidance,
               t.artifact_required_outputs AS artifact_required_outputs,
               t.artifact_optional_outputs AS artifact_optional_outputs,
               t.artifact_report_files AS artifact_report_files,
               t.reference_assets AS reference_assets,
               t.source_repo AS source_repo
        LIMIT $limit
        """,
        limit=limit,
    )
    return [dict(r) for r in result]


def query_file_search(tool: dict, store_name: str, top_k: int = 3) -> list[str]:
    """Query Google File Search for snippets related to the tool.

    Returns at most `top_k` snippets (truncated) or empty list on failure.
    """
    snippets: list[str] = []
    try:
        from google import genai
    except Exception:
        return snippets

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return snippets

    client = genai.Client(api_key=api_key)
    queries = [
        tool.get("id", ""),
        tool.get("name", ""),
        f"{tool.get('package', '')} {tool.get('name', '')}".strip(),
    ]
    for q in queries:
        if not q:
            continue
        try:
            resp = client.file_search_stores.query(name=store_name, query=q)
            for hit in resp.results[:top_k]:
                txt = getattr(hit, "text", None)
                if txt:
                    snippets.append(txt[:500])
        except Exception:
            continue
    return snippets


def build_tool_text(
    tool: dict,
    use_file_search: bool = False,
    store_name: str | None = None,
) -> str:
    """Build a text representation of a tool for embedding."""
    parts = []

    name = tool.get("name") or tool.get("id", "")
    parts.append(name)

    desc = tool.get("description")
    if desc:
        parts.append(desc)

    caps = tool.get("capabilities") or []
    if caps:
        parts.append("Capabilities: " + ", ".join(caps))

    pkg = tool.get("package")
    if pkg:
        parts.append(f"Package: {pkg}")

    intents = tool.get("intents") or []
    if intents:
        parts.append("Intents: " + ", ".join(intents))

    consumes = tool.get("consumes") or []
    if consumes:
        parts.append("Consumes: " + ", ".join(consumes))
    produces = tool.get("produces") or []
    if produces:
        parts.append("Produces: " + ", ".join(produces))

    stage = tool.get("stage")
    if stage:
        parts.append(f"Workflow stage: {stage}")
    cost_tier = tool.get("cost_tier")
    if cost_tier:
        parts.append(f"Cost tier: {cost_tier}")
    lifecycle = tool.get("lifecycle")
    if lifecycle:
        parts.append(f"Lifecycle: {lifecycle}")
    recipe_family = tool.get("recipe_family")
    if recipe_family:
        parts.append(f"Recipe family: {recipe_family}")

    supported_targets = tool.get("supported_recipe_targets") or []
    if supported_targets:
        parts.append("Supported recipe targets: " + ", ".join(supported_targets))
    primary_target = tool.get("primary_target")
    if primary_target:
        parts.append(f"Primary runtime target: {primary_target}")
    execution_story_kind = tool.get("execution_story_kind")
    if execution_story_kind:
        parts.append(f"Execution story kind: {execution_story_kind}")
    posture = tool.get("mcp_execution_posture")
    if posture:
        parts.append(f"MCP execution posture: {posture}")
    surface_class = tool.get("workflow_surface_class")
    if surface_class:
        parts.append(f"Workflow surface class: {surface_class}")
    if tool.get("recipe_first_workflow"):
        parts.append("Recipe-first workflow")
    if tool.get("heavy_runtime_workflow"):
        parts.append("Heavy runtime workflow")
    if tool.get("batch_analysis_workflow"):
        parts.append("Long-running batch-analysis workflow")

    recommended_entrypoint = tool.get("recommended_mcp_entrypoint")
    if recommended_entrypoint:
        parts.append(f"Recommended MCP entrypoint: {recommended_entrypoint}")
    guidance = tool.get("execution_guidance")
    if guidance:
        parts.append(guidance)

    artifact_required = tool.get("artifact_required_outputs") or []
    if artifact_required:
        parts.append("Required outputs: " + ", ".join(artifact_required))
    artifact_optional = tool.get("artifact_optional_outputs") or []
    if artifact_optional:
        parts.append("Optional outputs: " + ", ".join(artifact_optional))
    artifact_reports = tool.get("artifact_report_files") or []
    if artifact_reports:
        parts.append("Report files: " + ", ".join(artifact_reports))
    reference_assets = tool.get("reference_assets") or []
    if reference_assets:
        parts.append("Reference assets: " + ", ".join(reference_assets))
    source_repo = tool.get("source_repo")
    if source_repo:
        parts.append(f"Source repo: {source_repo}")

    base_text = ". ".join(parts)

    if use_file_search and store_name:
        snippets = query_file_search(tool, store_name, top_k=3)
        if snippets:
            base_text = (base_text + "\n\n" + "\n\n".join(snippets))[:4000]

    return base_text


def store_embeddings(session, tool_embeddings: list[tuple], field: str = "embedding"):
    """Store embeddings in Neo4j under the given field."""
    cypher = f"""
    UNWIND $rows AS row
    MATCH (t:Tool {{id: row.id}})
    SET t.{field} = row.embedding
    """
    session.run(
        cypher,
        rows=[{"id": tid, "embedding": emb.tolist()} for tid, emb in tool_embeddings],
    )


def main():
    parser = argparse.ArgumentParser(description="Generate tool embeddings")
    parser.add_argument(
        "--model",
        choices=["gemini", "sentence-transformer"],
        default="sentence-transformer",
        help="Embedding model to use",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for embedding generation",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximum number of tools to process",
    )
    parser.add_argument(
        "--embedding-field",
        default=os.environ.get("BR_EMBEDDING_FIELD", "embedding"),
        help="Neo4j property to write (embedding or embedding_v2)",
    )
    parser.add_argument(
        "--use-file-search",
        action="store_true",
        help="Enrich text with Google File Search snippets before embedding",
    )
    parser.add_argument(
        "--file-search-store",
        default=os.environ.get(
            "FILE_SEARCH_STORE",
            os.environ.get(
                "BR_FILE_SEARCH_STORE",
                "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj",
            ),
        ),
        help="Google File Search store name",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]

    embedding_field = args.embedding_field
    if embedding_field not in {"embedding", "embedding_v2"}:
        logger.warning(
            "Unsupported embedding field '%s', falling back to 'embedding'",
            embedding_field,
        )
        embedding_field = "embedding"

    logger.info(f"Loading embedding model: {args.model}")
    model = get_embedding_model(args.model)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    total_processed = 0

    with driver.session() as session:
        while True:
            tools = get_tools_without_embeddings(
                session, field=embedding_field, limit=args.batch_size
            )
            if not tools:
                logger.info("No more tools to process")
                break

            texts = [
                build_tool_text(
                    t,
                    use_file_search=args.use_file_search,
                    store_name=args.file_search_store,
                )
                for t in tools
            ]
            tool_ids = [t["id"] for t in tools]

            logger.info(f"Generating embeddings for {len(texts)} tools...")
            embeddings = embed_texts(model, texts, args.model)

            tool_embeddings = list(zip(tool_ids, embeddings, strict=False))
            store_embeddings(session, tool_embeddings, field=embedding_field)

            total_processed += len(tools)
            logger.info(f"Processed {total_processed} tools so far")

            if total_processed >= args.limit:
                logger.info(f"Reached limit of {args.limit} tools")
                break

    driver.close()
    logger.info(f"Done! Processed {total_processed} tools total")


if __name__ == "__main__":
    main()
